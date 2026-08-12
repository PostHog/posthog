from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from posthog.rate_limit import SupportSlackOAuthCallbackThrottle

from products.conversations.backend.api.slack_oauth import support_slack_oauth_callback


class TestSupportSlackOAuthCallbackThrottle(SimpleTestCase):
    @patch("products.conversations.backend.api.slack_oauth.requests.post")
    @patch.object(SupportSlackOAuthCallbackThrottle, "allow_request", return_value=False)
    def test_throttled_request_returns_429_before_token_exchange(self, _mock_allow, mock_post):
        request = RequestFactory().get("/api/conversations/v1/slack/callback", {"state": "x", "code": "y"})

        response = support_slack_oauth_callback(request)

        assert response.status_code == 429
        mock_post.assert_not_called()
