from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.plugins.plugin_server_api import validate_messaging_preferences_token

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
