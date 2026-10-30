"""Tests for the GitLab integration."""

import pytest
from unittest.mock import MagicMock, patch


class TestGitLabIntegrationSSRFProtection:
    """Test SSRF protections in GitLabIntegration."""

    @patch("requests.request")
    @patch("posthog.models.integration.gitlab.is_url_allowed")
    def test_get_uses_allow_redirects_false(self, mock_is_url_allowed, mock_get):
        """GET requests must use allow_redirects=False to prevent redirect-based SSRF bypass."""
        from posthog.models.integration import GitLabIntegration

        mock_is_url_allowed.return_value = (True, None)
        mock_get.return_value.json.return_value = {"data": "test"}

        GitLabIntegration.get("https://gitlab.com", "projects/1", "token123", endpoint="/api/v4/projects/{id}")

        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs.get("allow_redirects") is False, "GET must use allow_redirects=False for SSRF protection"

    @patch("requests.request")
    @patch("posthog.models.integration.gitlab.is_url_allowed")
    def test_post_uses_allow_redirects_false(self, mock_is_url_allowed, mock_post):
        """POST requests must use allow_redirects=False to prevent redirect-based SSRF bypass."""
        from posthog.models.integration import GitLabIntegration

        mock_is_url_allowed.return_value = (True, None)
        mock_post.return_value.json.return_value = {"data": "test"}

        GitLabIntegration.post(
            "https://gitlab.com",
            "projects/1/issues",
            "token123",
            {"title": "test"},
            endpoint="/api/v4/projects/{id}/issues",
        )

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs.get("allow_redirects") is False, "POST must use allow_redirects=False for SSRF protection"

    @patch("requests.request")
    @patch("posthog.models.integration.gitlab.is_url_allowed")
    def test_get_validates_url_before_request(self, mock_is_url_allowed, mock_get):
        """URL validation must happen before the request is made."""
        from posthog.models.integration import GitLabIntegration, GitLabIntegrationError

        mock_is_url_allowed.return_value = (False, "Private IP address not allowed")

        with pytest.raises(GitLabIntegrationError, match="Invalid GitLab hostname"):
            GitLabIntegration.get("http://192.168.1.1", "projects/1", "token123", endpoint="/api/v4/projects/{id}")

        mock_get.assert_not_called()

    @patch("requests.request")
    @patch("posthog.models.integration.gitlab.is_url_allowed", return_value=(True, None))
    def test_get_rejects_http_before_sending_credentials(self, _mock_is_url_allowed, mock_get):
        from posthog.models.integration import GitLabIntegration, GitLabIntegrationError

        with pytest.raises(GitLabIntegrationError, match="HTTPS is required"):
            GitLabIntegration.get(
                "http://gitlab.example.com", "projects/1", "token123", endpoint="/api/v4/projects/{id}"
            )

        mock_get.assert_not_called()

    @patch("requests.request")
    @patch("posthog.models.integration.gitlab.is_url_allowed")
    def test_post_validates_url_before_request(self, mock_is_url_allowed, mock_post):
        """URL validation must happen before the request is made."""
        from posthog.models.integration import GitLabIntegration, GitLabIntegrationError

        mock_is_url_allowed.return_value = (False, "Private IP address not allowed")

        with pytest.raises(GitLabIntegrationError, match="Invalid GitLab hostname"):
            GitLabIntegration.post(
                "http://192.168.1.1",
                "projects/1/issues",
                "token123",
                {"title": "test"},
                endpoint="/api/v4/projects/{id}/issues",
            )

        mock_post.assert_not_called()


class TestGitLabIntegrationModel:
    @patch("requests.request")
    @patch("posthog.models.integration.gitlab.is_url_allowed", return_value=(True, None))
    def test_search_issues_filters_by_issue_id(self, _mock_is_url_allowed, mock_get):
        from posthog.models.integration import GitLabIntegration

        integration = MagicMock(
            kind="gitlab",
            config={"hostname": "https://gitlab.com", "project_id": 1},
            sensitive_config={"access_token": "token123"},
        )
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "iid": 42,
            "title": "Checkout failed",
            "web_url": "https://gitlab.com/acme/app/-/issues/42",
        }

        results = GitLabIntegration(integration).search_issues("#42")

        assert results[0]["id"] == "42"
        assert mock_get.call_args.args[1] == "https://gitlab.com/api/v4/projects/1/issues/42"
        assert "params" not in mock_get.call_args.kwargs

    @patch("requests.request")
    @patch("posthog.models.integration.gitlab.is_url_allowed", return_value=(True, None))
    def test_search_issues_falls_back_to_title_search_when_issue_id_is_not_found(self, _mock_is_url_allowed, mock_get):
        from posthog.models.integration import GitLabIntegration

        integration = MagicMock(
            kind="gitlab",
            config={"hostname": "https://gitlab.com", "project_id": 1},
            sensitive_config={"access_token": "token123"},
        )
        issue_id_response = MagicMock(status_code=404)
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

    @patch("requests.request")
    @patch("posthog.models.integration.gitlab.is_url_allowed", return_value=(True, None))
    def test_create_issue_sends_assignee_as_numeric_id(self, _mock_is_url_allowed, mock_post):
        from posthog.models.integration import GitLabIntegration

        integration = MagicMock(
            kind="gitlab",
            config={"hostname": "https://gitlab.com", "project_id": 1},
            sensitive_config={"access_token": "token123"},
        )
        mock_post.return_value.json.return_value = {"iid": 7}

        GitLabIntegration(integration).create_issue({"title": "Checkout failed", "body": "Details", "assignee": "42"})

        assert mock_post.call_args.kwargs["json"]["assignee_ids"] == [42]

    @patch("requests.request")
    @patch("posthog.models.integration.gitlab.is_url_allowed", return_value=(True, None))
    def test_list_assignees_searches_and_skips_inactive_members(self, _mock_is_url_allowed, mock_get):
        from posthog.models.integration import GitLabIntegration

        integration = MagicMock(
            kind="gitlab",
            config={"hostname": "https://gitlab.com", "project_id": 1},
            sensitive_config={"access_token": "token123"},
        )
        mock_get.return_value.json.return_value = [
            {"id": 1, "username": "ada", "name": "Ada", "state": "active"},
            {"id": 2, "username": "gone", "name": "Gone", "state": "blocked"},
        ]

        from posthog.models.integration import Assignee

        assert GitLabIntegration(integration).list_assignees("ad") == [Assignee(id="1", name="Ada")]
        assert mock_get.call_args.args[1] == (
            "https://gitlab.com/api/v4/projects/1/members/all?state=active&per_page=100&query=ad"
        )

    @patch("requests.request")
    @patch("posthog.models.integration.gitlab.is_url_allowed", return_value=(True, None))
    def test_list_assignees_reports_the_gitlab_error(self, _mock_is_url_allowed, mock_get):
        from posthog.models.integration import AssigneeLookupFailed, GitLabIntegration

        integration = MagicMock(
            kind="gitlab",
            config={"hostname": "https://gitlab.com", "project_id": 1},
            sensitive_config={"access_token": "token123"},
        )
        mock_get.return_value.json.return_value = {"message": "403 Forbidden"}

        with pytest.raises(AssigneeLookupFailed, match="403 Forbidden"):
            GitLabIntegration(integration).list_assignees()

    @patch("requests.request")
    @patch("posthog.models.integration.gitlab.is_url_allowed", return_value=(True, None))
    def test_list_projects_follows_next_page_header(self, _mock_is_url_allowed, mock_request):
        from posthog.models.integration import GitLabIntegration

        integration = MagicMock(
            kind="gitlab",
            config={"hostname": "https://gitlab.com"},
            sensitive_config={"access_token": "token123"},
        )
        first_page = MagicMock(status_code=200, headers={"X-Next-Page": "2"})
        first_page.json.return_value = [
            {"id": 1, "path_with_namespace": "acme/app", "web_url": "https://gitlab.com/acme/app"}
        ]
        last_page = MagicMock(status_code=200, headers={"X-Next-Page": ""})
        last_page.json.return_value = [
            {
                "id": 2,
                "path_with_namespace": "acme/platform/api",
                "web_url": "https://gitlab.com/acme/platform/api",
                "default_branch": "main",
            }
        ]
        mock_request.side_effect = [first_page, last_page]

        projects = GitLabIntegration(integration).list_projects()

        assert [project.path_with_namespace for project in projects] == ["acme/app", "acme/platform/api"]
        assert [call.kwargs["params"]["page"] for call in mock_request.call_args_list] == ["1", "2"]

    @patch("requests.request")
    @patch("posthog.models.integration.gitlab.is_url_allowed", return_value=(True, None))
    def test_create_merge_request_opens_a_draft(self, _mock_is_url_allowed, mock_request):
        from posthog.models.integration import GitLabIntegration

        integration = MagicMock(
            kind="gitlab",
            config={"hostname": "https://gitlab.com"},
            sensitive_config={"access_token": "token123"},
        )
        mock_request.return_value = MagicMock(status_code=201)
        mock_request.return_value.json.return_value = {
            "iid": 5,
            "web_url": "https://gitlab.com/acme/app/-/merge_requests/5",
            "state": "opened",
            "draft": True,
        }

        merge_request = GitLabIntegration(integration).create_merge_request(
            7, source_branch="posthog/fix-checkout", target_branch="main", title="Fix checkout", description="Details"
        )

        assert merge_request.iid == 5
        assert mock_request.call_args.args[1] == "https://gitlab.com/api/v4/projects/7/merge_requests"
        assert mock_request.call_args.kwargs["json"]["title"] == "Draft: Fix checkout"
        assert mock_request.call_args.kwargs["allow_redirects"] is False

    @patch("requests.request")
    @patch("posthog.models.integration.gitlab.is_url_allowed", return_value=(True, None))
    def test_an_encoded_project_path_never_reaches_the_endpoint_label(self, _mock_is_url_allowed, mock_request):
        from prometheus_client import REGISTRY

        from posthog.models.integration import GitLabIntegration

        mock_request.return_value = MagicMock(status_code=200, headers={})

        GitLabIntegration.get(
            "https://gitlab.com", "projects/acme%2Fsecret-app", "token123", endpoint="/api/v4/projects/{id}"
        )

        endpoints = {
            sample.labels["endpoint"]
            for metric in REGISTRY.collect()
            if metric.name == "gitlab_api_requests"
            for sample in metric.samples
        }
        assert "/api/v4/projects/{id}" in endpoints
        assert not any("secret-app" in endpoint for endpoint in endpoints)
