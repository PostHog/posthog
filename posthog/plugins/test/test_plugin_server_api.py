import json

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.plugins.plugin_server_api import (
    WORKFLOWS_MANUAL_RUN_JWT_PURPOSE,
    WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_PURPOSE,
    create_hog_flow_manual_invocation,
    prepare_transactional_email_attachment_uploads,
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
            (
                "template_send",
                lambda: send_transactional_email(7, "flow-1", {"to": "user@example.com"}),
                "/api/projects/7/hog_flows/flow-1/transactional_email",
                "flow-1",
                None,
            ),
            (
                "code_send",
                lambda: send_accepted_transactional_email(7, "flow-1", {"to": "user@example.com"}),
                "/api/projects/7/hog_flows/flow-1/transactional_email/send",
                "flow-1",
                "code_send",
            ),
            (
                "attachment_upload",
                lambda: prepare_transactional_email_attachment_uploads(7, {"files": []}),
                "/api/projects/7/transactional_email/attachments/uploads",
                None,
                "attachment_upload",
            ),
        ]
    )
    @patch("posthog.plugins.plugin_server_api.internal_requests")
    def test_mints_a_token_only_its_own_route_accepts(
        self, _name, request, path, hog_flow_id, kind, mock_internal_requests
    ):
        request()

        url, headers = (
            mock_internal_requests.post.call_args.args[0],
            mock_internal_requests.post.call_args.kwargs["headers"],
        )
        claims = WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_PURPOSE.verify(headers["Authorization"].removeprefix("Bearer "))
        self.assertTrue(url.endswith(path))
        self.assertEqual((claims["team_id"], claims.get("hog_flow_id"), claims.get("kind")), (7, hog_flow_id, kind))

    @patch("posthog.plugins.plugin_server_api.internal_requests")
    def test_a_code_send_posts_text_outside_ascii_as_utf8(self, mock_internal_requests):
        payload = {"send": {"content": {"subject": "注文", "html": "<p>注文 🎉</p>"}}}

        send_accepted_transactional_email(7, "flow-1", payload)

        body = mock_internal_requests.post.call_args.kwargs["data"]
        self.assertEqual(json.loads(body), payload)
        self.assertIn("<p>注文 🎉</p>".encode(), body)


@override_settings(WORKFLOWS_CANCEL_JWT_SECRETS=["test-manual-run-key"])
class TestManualRunToken(SimpleTestCase):
    @patch("posthog.plugins.plugin_server_api.internal_requests")
    def test_mints_a_token_bound_to_the_user_it_runs_for(self, mock_internal_requests):
        create_hog_flow_manual_invocation(7, "flow-1", "user@example.com", {"name": "Ada"})

        url, kwargs = mock_internal_requests.post.call_args.args[0], mock_internal_requests.post.call_args.kwargs
        claims = WORKFLOWS_MANUAL_RUN_JWT_PURPOSE.verify(kwargs["headers"]["Authorization"].removeprefix("Bearer "))
        self.assertTrue(url.endswith("/api/projects/7/hog_flows/flow-1/manual_invocations"))
        self.assertEqual(
            (claims["team_id"], claims["hog_flow_id"], claims["user_id"]), (7, "flow-1", "user@example.com")
        )
        self.assertEqual(kwargs["json"], {"user_id": "user@example.com", "variables": {"name": "Ada"}})
