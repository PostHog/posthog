"""Tests for the GitLab integration."""

import pytest
from unittest.mock import MagicMock, patch


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

    @patch("posthog.models.integration.gitlab.requests.get")
    @patch("posthog.models.integration.gitlab.is_url_allowed", return_value=(True, None))
    def test_get_rejects_http_before_sending_credentials(self, _mock_is_url_allowed, mock_get):
        from posthog.models.integration import GitLabIntegration, GitLabIntegrationError

        with pytest.raises(GitLabIntegrationError, match="HTTPS is required"):
            GitLabIntegration.get("http://gitlab.example.com", "projects/1", "token123")

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


class TestGitLabIntegrationModel:
    @patch("posthog.models.integration.gitlab.requests.get")
    @patch("posthog.models.integration.gitlab.is_url_allowed", return_value=(True, None))
    def test_search_issues_filters_by_issue_id(self, _mock_is_url_allowed, mock_get):
        from posthog.models.integration import GitLabIntegration

        integration = MagicMock(
            kind="gitlab",
            config={"hostname": "https://gitlab.com", "project_id": 1},
            sensitive_config={"access_token": "token123"},
        )
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = [
            {"iid": 42, "title": "Checkout failed", "web_url": "https://gitlab.com/acme/app/-/issues/42"}
        ]

        results = GitLabIntegration(integration).search_issues("#42")

        assert results[0]["id"] == "42"
        assert mock_get.call_args.kwargs["params"]["iids[]"] == 42
        assert "search" not in mock_get.call_args.kwargs["params"]

    @patch("posthog.models.integration.gitlab.requests.get")
    @patch("posthog.models.integration.gitlab.is_url_allowed", return_value=(True, None))
    def test_search_issues_falls_back_to_title_search_when_issue_id_is_not_found(self, _mock_is_url_allowed, mock_get):
        from posthog.models.integration import GitLabIntegration

        integration = MagicMock(
            kind="gitlab",
            config={"hostname": "https://gitlab.com", "project_id": 1},
            sensitive_config={"access_token": "token123"},
        )
        issue_id_response = MagicMock(status_code=200)
        issue_id_response.json.return_value = []
        title_response = MagicMock(status_code=200)
        title_response.json.return_value = [
            {"iid": 84, "title": "Migration for #42", "web_url": "https://gitlab.com/acme/app/-/issues/84"}
        ]
        mock_get.side_effect = [issue_id_response, title_response]

        results = GitLabIntegration(integration).search_issues("#42")

        assert [result["id"] for result in results] == ["84"]
        assert mock_get.call_count == 2
        assert mock_get.call_args.kwargs["params"]["search"] == "#42"
        assert "iids[]" not in mock_get.call_args.kwargs["params"]
