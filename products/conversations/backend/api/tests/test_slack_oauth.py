import json

from unittest.mock import patch

from django.core import signing
from django.test import RequestFactory, SimpleTestCase

from posthog.credentials_service.errors import CredentialsServiceUnreachableError
from posthog.models.user import User
from posthog.rate_limit import SupportSlackOAuthCallbackThrottle

from products.conversations.backend.api.slack_oauth import STATE_SALT, support_slack_oauth_callback


class TestSupportSlackOAuthCallbackThrottle(SimpleTestCase):
    @patch("products.conversations.backend.api.slack_oauth.slack_request")
    @patch.object(SupportSlackOAuthCallbackThrottle, "allow_request", return_value=False)
    def test_throttled_request_returns_429_before_token_exchange(self, _mock_allow, mock_post):
        request = RequestFactory().get("/api/conversations/v1/slack/callback", {"state": "x", "code": "y"})

        response = support_slack_oauth_callback(request)

        assert response.status_code == 429
        mock_post.assert_not_called()


class TestSupportSlackOAuthCallbackCredentialsOutage(SimpleTestCase):
    @patch("products.conversations.backend.api.slack_oauth.slack_request")
    @patch(
        "products.conversations.backend.api.slack_oauth.get_many_or_instance_settings",
        side_effect=CredentialsServiceUnreachableError("refused"),
    )
    @patch.object(SupportSlackOAuthCallbackThrottle, "allow_request", return_value=True)
    def test_credentials_service_failure_returns_retryable_error(self, _mock_allow, _mock_settings, mock_post):
        state = signing.dumps({"user_id": 1, "team_id": 1}, salt=STATE_SALT)
        request = RequestFactory().get("/api/conversations/v1/slack/callback", {"state": state, "code": "y"})
        request.user = User(id=1)

        response = support_slack_oauth_callback(request)

        assert response.status_code == 503
        assert json.loads(response.content) == {"error": "support_slack_unavailable"}
        mock_post.assert_not_called()
