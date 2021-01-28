# -*- coding: utf-8 -*-
# Copyright: (c) 2021, XLAB Steampunk <steampunk@xlab.si>
#
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json

from ansible.module_utils.six.moves.urllib.error import HTTPError, URLError
from ansible.module_utils.six.moves.urllib.parse import urlencode, quote
from ansible.module_utils.urls import Request, basic_auth_header

from .errors import ServiceNowError, AuthError, UnexpectedAPIResponse


class Response:
    def __init__(self, status, data, headers=None):
        self.status = status
        self.data = data
        # [('h1', 'v1'), ('h2', 'v2')] -> {'h1': 'v1', 'h2': 'v2'}
        self.headers = dict(headers) if headers else {}

        self._json = None

    @property
    def json(self):
        if self._json is None:
            try:
                self._json = json.loads(self.data)
            except ValueError:
                raise ServiceNowError(
                    "Received invalid JSON response: {0}".format(self.data)
                )
        return self._json


class Client:
    def __init__(self, host, username, password, client_id=None, client_secret=None):
        self.host = host
        self.username = username
        self.password = password
        self.client_id = client_id
        self.client_secret = client_secret

        self._auth_header = None
        self._client = Request()

    @property
    def auth_header(self):
        if not self._auth_header:
            self._auth_header = self._login()
        return self._auth_header

    def _login(self):
        if self.client_id and self.client_secret:
            return self._login_oauth()
        return self._login_username_password()

    def _login_username_password(self):
        return dict(Authorization=basic_auth_header(self.username, self.password))

    def _login_oauth(self):
        auth_data = urlencode(
            dict(
                grant_type="password",
                username=self.username,
                password=self.password,
                client_id=self.client_id,
                client_secret=self.client_secret,
            )
        )
        resp = self._request(
            "POST",
            "{0}/oauth_token.do".format(self.host),
            data=auth_data,
            headers=dict(Accept="application/json"),
        )
        if resp.status != 200:
            raise UnexpectedAPIResponse(resp.status, resp.data)

        access_token = resp.json["access_token"]
        return dict(Authorization="Bearer {0}".format(access_token))

    def _request(self, method, path, data=None, headers=None):
        try:
            raw_resp = self._client.open(method, path, data=data, headers=headers)
        except HTTPError as e:
            # Wrong username/password, or expired access token
            if e.code == 401:
                raise AuthError(
                    "Failed to authenticate with the instance: {0} {1}".format(
                        e.code, e.reason
                    ),
                )
            # Other HTTP error codes do not necessarily mean errors.
            # This is for the caller to decide.
            return Response(e.code, e.reason)
        except URLError as e:
            raise ServiceNowError(e.reason)

        return Response(raw_resp.status, raw_resp.read(), raw_resp.getheaders())

    def request(self, method, path, data=None):
        escaped_path = quote(path.rstrip("/"))
        url = "{0}/api/now/{1}".format(self.host, escaped_path)
        headers = dict(Accept="application/json", **self.auth_header)
        if data is not None:
            data = json.dumps(data, separators=(",", ":"))
            headers["Content-type"] = "application/json"
        return self._request(method, url, data=data, headers=headers)

    def get(self, path):
        resp = self.request("GET", path)
        if resp.status in (200, 404):
            return resp
        raise UnexpectedAPIResponse(resp.status, resp.data)

    def post(self, path, data):
        resp = self.request("POST", path, data=data)
        if resp.status == 201:
            return resp
        raise UnexpectedAPIResponse(resp.status, resp.data)

    def put(self, path, data):
        resp = self.request("PUT", path, data=data)
        if resp.status == 200:
            return resp
        raise UnexpectedAPIResponse(resp.status, resp.data)

    def delete(self, path):
        resp = self.request("DELETE", path)
        if resp.status != 204:
            raise UnexpectedAPIResponse(resp.status, resp.data)
