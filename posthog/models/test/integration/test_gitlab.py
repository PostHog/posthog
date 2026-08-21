"""Tests for the GitLab integration."""

import pytest
from unittest.mock import patch


class TestGitLabIntegrationSSRFProtection:
    """Test SSRF protections in GitLabIntegration."""

    @patch("posthog.models.integration.gitlab.requests.get")
    @patch("posthog.models.integration.gitlab.is_url_allowed")
    def test_get_uses_allow_redirects_false(self, mock_is_url_allowed, mock_get):
        """GET requests must use allow_redirects=False to prevent redirect-based SSRF bypass."""
        from posthog.models.integration import GitLabIntegration

        mock_is_url_allowed.return_value = (True, None)
        mock_get.return_value.json.return_value = {"data": "test"}

        GitLabIntegration.get("https://gitlab.com", "projects/1", "token123")

        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs.get("allow_redirects") is False, "GET must use allow_redirects=False for SSRF protection"

    @patch("posthog.models.integration.gitlab.requests.post")
    @patch("posthog.models.integration.gitlab.is_url_allowed")
    def test_post_uses_allow_redirects_false(self, mock_is_url_allowed, mock_post):
        """POST requests must use allow_redirects=False to prevent redirect-based SSRF bypass."""
        from posthog.models.integration import GitLabIntegration

        mock_is_url_allowed.return_value = (True, None)
        mock_post.return_value.json.return_value = {"data": "test"}

        GitLabIntegration.post("https://gitlab.com", "projects/1/issues", "token123", {"title": "test"})

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs.get("allow_redirects") is False, "POST must use allow_redirects=False for SSRF protection"

    @patch("posthog.models.integration.gitlab.requests.get")
    @patch("posthog.models.integration.gitlab.is_url_allowed")
    def test_get_validates_url_before_request(self, mock_is_url_allowed, mock_get):
        """URL validation must happen before the request is made."""
        from posthog.models.integration import GitLabIntegration, GitLabIntegrationError

        mock_is_url_allowed.return_value = (False, "Private IP address not allowed")

        with pytest.raises(GitLabIntegrationError, match="Invalid GitLab hostname"):
            GitLabIntegration.get("http://192.168.1.1", "projects/1", "token123")

        mock_get.assert_not_called()

    @patch("posthog.models.integration.gitlab.requests.post")
    @patch("posthog.models.integration.gitlab.is_url_allowed")
    def test_post_validates_url_before_request(self, mock_is_url_allowed, mock_post):
        """URL validation must happen before the request is made."""
        from posthog.models.integration import GitLabIntegration, GitLabIntegrationError

        mock_is_url_allowed.return_value = (False, "Private IP address not allowed")

        with pytest.raises(GitLabIntegrationError, match="Invalid GitLab hostname"):
            GitLabIntegration.post("http://192.168.1.1", "projects/1/issues", "token123", {"title": "test"})

        mock_post.assert_not_called()
