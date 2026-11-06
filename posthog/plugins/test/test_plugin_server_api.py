import json

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.plugins.plugin_server_api import (
    WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_PURPOSE,
    send_accepted_transactional_email,
    send_transactional_email,
    validate_messaging_preferences_token,
)

VALID_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJ0ZWFtX2lkIjoxLCJpZGVudGlmaWVyIjoiYUBiLmNvbSJ9.c2ln"


class TestValidateMessagingPreferencesToken(SimpleTestCase):
    @parameterized.expand(
        [
            ("path_traversal", "../../hog_functions/states?teamId=1"),
            ("leading_slash", "/api/hog_functions/states"),
            ("query_injection", "x?teamId=1"),
            ("fragment", "x#frag"),
            ("empty", ""),
            ("not_a_jwt", "just-one-segment"),
        ]
    )
    @patch("posthog.plugins.plugin_server_api.internal_requests")
    def test_malformed_token_never_calls_cdp(self, _name, token, mock_internal_requests):
        response = validate_messaging_preferences_token(token)

        mock_internal_requests.get.assert_not_called()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "Invalid recipient token"})

    @patch("posthog.plugins.plugin_server_api.internal_requests")
    def test_valid_token_calls_cdp_at_unaltered_path(self, mock_internal_requests):
        validate_messaging_preferences_token(VALID_TOKEN)

        mock_internal_requests.get.assert_called_once()
        called_url = mock_internal_requests.get.call_args.args[0]
        self.assertTrue(called_url.endswith(f"/api/messaging/validate_preferences_token/{VALID_TOKEN}"))


@override_settings(WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRETS=["test-transactional-email-key"])
class TestTransactionalEmailTokens(SimpleTestCase):
    @parameterized.expand(
        [
            ("template_send", send_transactional_email, "/transactional_email", None),
            ("code_send", send_accepted_transactional_email, "/transactional_email/send", "code_send"),
        ]
    )
    @patch("posthog.plugins.plugin_server_api.internal_requests")
    def test_mints_a_token_only_its_own_route_accepts(self, _name, send, path, kind, mock_internal_requests):
        send(7, "flow-1", {"to": "user@example.com"})

        url, headers = (
            mock_internal_requests.post.call_args.args[0],
            mock_internal_requests.post.call_args.kwargs["headers"],
        )
        claims = WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_PURPOSE.verify(headers["Authorization"].removeprefix("Bearer "))
        self.assertTrue(url.endswith(f"/api/projects/7/hog_flows/flow-1{path}"))
        self.assertEqual((claims["team_id"], claims["hog_flow_id"], claims.get("kind")), (7, "flow-1", kind))

    @patch("posthog.plugins.plugin_server_api.internal_requests")
    def test_a_code_send_posts_text_outside_ascii_as_utf8(self, mock_internal_requests):
        payload = {"send": {"content": {"subject": "注文", "html": "<p>注文 🎉</p>"}}}

        send_accepted_transactional_email(7, "flow-1", payload)

        body = mock_internal_requests.post.call_args.kwargs["data"]
        self.assertEqual(json.loads(body), payload)
        self.assertIn("<p>注文 🎉</p>".encode(), body)
