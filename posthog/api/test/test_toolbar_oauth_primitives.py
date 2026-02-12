import json
from urllib.parse import parse_qs, urlparse

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from rest_framework import status


@override_settings(TOOLBAR_OAUTH_ENABLED=True)
class TestToolbarOAuthPrimitives(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.app_urls = ["https://example.com"]
        self.team.save()

    def _start(self) -> dict:
        response = self.client.post(
            "/api/user/toolbar_oauth_start/",
            data=json.dumps(
                {
                    "app_url": self.team.app_urls[0],
                    "code_challenge": "test_challenge_value",
                    "code_challenge_method": "S256",
                    "user_intent": "edit-action",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_200_OK, response.content
        return response.json()

    @override_settings(TOOLBAR_OAUTH_ENABLED=False)
    def test_start_disabled(self):
        response = self.client.post(
            "/api/user/toolbar_oauth_start/",
            data=json.dumps({"app_url": self.team.app_urls[0], "code_challenge": "x", "code_challenge_method": "S256"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_start_returns_authorization_url(self):
        data = self._start()
        self.assertIn("authorization_url", data)

        parsed = urlparse(data["authorization_url"])
        qs = parse_qs(parsed.query)
        self.assertIn("state", qs)
        self.assertEqual(qs["code_challenge_method"][0], "S256")

    def test_start_rejects_unallowed_url(self):
        response = self.client.post(
            "/api/user/toolbar_oauth_start/",
            data=json.dumps(
                {
                    "app_url": "https://not-allowed.example.com",
                    "code_challenge": "test_challenge_value",
                    "code_challenge_method": "S256",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    @patch("posthog.api.oauth.toolbar_service.requests.post")
    def test_exchange_success(self, mock_post):
        start_data = self._start()
        state = parse_qs(urlparse(start_data["authorization_url"]).query)["state"][0]

        mock_post.return_value.status_code = 200
        mock_post.return_value.content = b'{"access_token":"pha_abc","refresh_token":"phr_abc","token_type":"Bearer","expires_in":3600,"scope":"openid"}'
        mock_post.return_value.json.return_value = {
            "access_token": "pha_abc",
            "refresh_token": "phr_abc",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "openid",
        }

        response = self.client.post(
            "/api/user/toolbar_oauth_exchange/",
            data=json.dumps({"code": "test_code", "state": state, "code_verifier": "test_verifier"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["access_token"], "pha_abc")

    @patch("posthog.api.oauth.toolbar_service.requests.post")
    def test_exchange_replay_fails(self, mock_post):
        start_data = self._start()
        state = parse_qs(urlparse(start_data["authorization_url"]).query)["state"][0]

        mock_post.return_value.status_code = 200
        mock_post.return_value.content = b'{"access_token":"pha_abc","refresh_token":"phr_abc","token_type":"Bearer","expires_in":3600,"scope":"openid"}'
        mock_post.return_value.json.return_value = {
            "access_token": "pha_abc",
            "refresh_token": "phr_abc",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "openid",
        }

        first = self.client.post(
            "/api/user/toolbar_oauth_exchange/",
            data=json.dumps({"code": "test_code", "state": state, "code_verifier": "test_verifier"}),
            content_type="application/json",
        )
        self.assertEqual(first.status_code, 200)

        second = self.client.post(
            "/api/user/toolbar_oauth_exchange/",
            data=json.dumps({"code": "test_code", "state": state, "code_verifier": "test_verifier"}),
            content_type="application/json",
        )
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.json()["code"], "state_replay")
