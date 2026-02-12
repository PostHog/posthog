import json
from urllib.parse import parse_qs, urlparse

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from rest_framework import status

from posthog.api.oauth.toolbar_service import CALLBACK_PATH, get_or_create_toolbar_oauth_application
from posthog.models import Organization, User


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

    def test_start_rejects_invalid_json_body(self):
        response = self.client.post(
            "/api/user/toolbar_oauth_start/",
            data="{not-json",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_json")

    def test_oauth_application_is_scoped_per_organization(self):
        base_url = "https://us.posthog.example"

        first_app = get_or_create_toolbar_oauth_application(base_url=base_url, user=self.user)

        other_org = Organization.objects.create(name="Another org")
        other_user = User.objects.create_user(
            email="toolbar-oauth-another-org@example.com",
            first_name="Other",
            password="password",
        )
        other_org.members.add(other_user)
        second_app = get_or_create_toolbar_oauth_application(base_url=base_url, user=other_user)

        self.assertNotEqual(first_app.id, second_app.id)
        self.assertEqual(first_app.organization, self.organization)
        self.assertEqual(second_app.organization, other_org)

    def test_oauth_application_supports_multiple_redirect_uris_within_org(self):
        first_base_url = "https://us.posthog.example"
        second_base_url = "https://eu.posthog.example"

        first_app = get_or_create_toolbar_oauth_application(base_url=first_base_url, user=self.user)
        second_app = get_or_create_toolbar_oauth_application(base_url=second_base_url, user=self.user)

        self.assertEqual(first_app.id, second_app.id)
        second_app.refresh_from_db()

        redirect_uris = {uri for uri in second_app.redirect_uris.split(" ") if uri}
        self.assertSetEqual(
            redirect_uris,
            {
                f"{first_base_url}{CALLBACK_PATH}",
                f"{second_base_url}{CALLBACK_PATH}",
            },
        )

    def test_callback_renders_bridge_with_code_and_state(self):
        response = self.client.get("/toolbar_oauth/callback?code=test_code&state=test_state")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "openerWindow.postMessage")
        self.assertContains(response, '"code": "test_code"')
        self.assertContains(response, '"state": "test_state"')

    def test_callback_renders_bridge_with_error_payload(self):
        response = self.client.get(
            "/toolbar_oauth/callback?error=access_denied&error_description=user+cancelled&state=test_state"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '"error": "access_denied"')
        self.assertContains(response, '"error_description": "user cancelled"')
        self.assertContains(response, '"state": "test_state"')

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

    def test_exchange_rejects_invalid_json_body(self):
        response = self.client.post(
            "/api/user/toolbar_oauth_exchange/",
            data="{not-json",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_json")

    @patch("posthog.api.oauth.toolbar_service.requests.post")
    def test_exchange_returns_error_for_non_json_token_response(self, mock_post):
        start_data = self._start()
        state = parse_qs(urlparse(start_data["authorization_url"]).query)["state"][0]

        mock_post.return_value.status_code = 502
        mock_post.return_value.content = b"bad gateway html"
        mock_post.return_value.json.side_effect = ValueError("invalid json")

        response = self.client.post(
            "/api/user/toolbar_oauth_exchange/",
            data=json.dumps({"code": "test_code", "state": state, "code_verifier": "test_verifier"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["code"], "token_exchange_invalid_response")

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
