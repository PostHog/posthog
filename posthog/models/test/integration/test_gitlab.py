"""Tests for the GitLab integration."""

import pytest
from unittest.mock import MagicMock, patch

import requests


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

        mock_is_url_allowed.return_value = (False, "Disallowed target IP: 10.1.2.3")

        with pytest.raises(GitLabIntegrationError, match="Invalid GitLab hostname") as rejection:
            GitLabIntegration.get(
                "https://gitlab.internal.example.com", "projects/1", "token123", endpoint="/api/v4/projects/{id}"
            )

        # Setup turns this error into a 400 body, so the resolved address must not travel with it.
        assert "10.1.2.3" not in str(rejection.value)
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
    @pytest.mark.parametrize(
        "response, expected_error",
        [
            (MagicMock(status_code=301), "HTTP 301"),
            (MagicMock(status_code=401), "HTTP 401"),
            (
                MagicMock(status_code=200, **{"json.side_effect": requests.JSONDecodeError("Expecting value", "", 0)}),
                "isn't JSON",
            ),
            (requests.ConnectionError("Name or service not known"), "Couldn't connect"),
        ],
        ids=["redirect", "unauthorized", "html_body", "unreachable_host"],
    )
    @patch("requests.request")
    @patch("posthog.models.integration.gitlab.is_url_allowed", return_value=(True, None))
    def test_create_integration_rejects_a_host_that_does_not_answer_like_gitlab(
        self, _mock_is_url_allowed, mock_request, response, expected_error
    ):
        from prometheus_client import REGISTRY

        from posthog.egress.gitlab.transport import token_scope
        from posthog.models.integration import GitLabIntegration, GitLabIntegrationError

        if isinstance(response, Exception):
            mock_request.side_effect = response
        else:
            mock_request.return_value = response

        with pytest.raises(GitLabIntegrationError, match=expected_error):
            GitLabIntegration.create_integration("https://gitlab.example.com", "1", "token123", 1, None)

        # A rejected token is never stored, so scoping the setup probe would let repeated attempts
        # retain one counter child and three gauge children per token for the life of the process.
        rejected_scope = token_scope("https://gitlab.example.com", "token123")
        samples = (
            sample for metric in REGISTRY.collect() if metric.name.startswith("gitlab_api") for sample in metric.samples
        )
        assert not any(sample.labels.get("scope") == rejected_scope for sample in samples)

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

    @patch("posthog.models.integration.gitlab.time.monotonic", side_effect=[1.0, 11.0])
    @patch("posthog.models.integration.gitlab.GitLabIntegration._request")
    def test_project_listing_stops_at_deadline(self, mock_request, _clock):
        from posthog.models.integration import GitLabIntegration, GitLabIntegrationError

        integration = MagicMock(
            kind="gitlab", config={"hostname": "https://gitlab.com"}, sensitive_config={"access_token": "token123"}
        )
        mock_request.return_value = MagicMock(status_code=200, headers={"X-Next-Page": "2"})
        mock_request.return_value.json.return_value = []
        with pytest.raises(GitLabIntegrationError, match="Try again"):
            GitLabIntegration(integration).list_projects(deadline=10.0)
        assert mock_request.call_count == 1
        assert mock_request.call_args.kwargs["timeout"] == 9.0

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

    @pytest.mark.parametrize(
        "status_code, permissions, expected_path",
        [
            (200, {"project_access": {"access_level": 30}, "group_access": None}, "acme/platform/api"),
            (200, {"project_access": None, "group_access": {"access_level": 40}}, "acme/platform/api"),
            (200, {"project_access": {"access_level": 20}, "group_access": None}, None),
            (404, None, None),
        ],
        ids=["project_developer", "group_maintainer", "project_reporter", "not_found"],
    )
    @patch("requests.request")
    @patch("posthog.models.integration.gitlab.is_url_allowed", return_value=(True, None))
    def test_get_pushable_project_needs_the_developer_role(
        self, _mock_is_url_allowed, mock_request, status_code, permissions, expected_path
    ):
        from posthog.models.integration import GitLabIntegration

        integration = MagicMock(
            kind="gitlab", config={"hostname": "https://gitlab.com"}, sensitive_config={"access_token": "token123"}
        )
        mock_request.return_value = MagicMock(status_code=status_code)
        mock_request.return_value.json.return_value = {
            "id": 7,
            "path_with_namespace": "acme/platform/api",
            "web_url": "https://gitlab.com/acme/platform/api",
            "default_branch": "main",
            "permissions": permissions,
        }

        project = GitLabIntegration(integration).get_pushable_project("acme/platform/api")

        assert (project.path_with_namespace if project else None) == expected_path
        assert mock_request.call_args.args[1] == "https://gitlab.com/api/v4/projects/acme%2Fplatform%2Fapi"
        assert mock_request.call_args.kwargs["headers"]["Authorization"] == "Bearer token123"

    @pytest.mark.parametrize(
        "status_code, payload, expected",
        [
            (
                200,
                {"scopes": ["read_api"], "expires_at": "2027-01-31"},
                ("2027-01-31", ("api",)),
            ),
            (200, {"scopes": ["api"], "expires_at": None}, (None, ())),
            (404, {"message": "404 Not Found"}, None),
        ],
        ids=["read_only_token", "task_ready_token", "endpoint_missing_on_old_instance"],
    )
    @patch("requests.request")
    @patch("posthog.models.integration.gitlab.is_url_allowed", return_value=(True, None))
    def test_pasted_token_describe(self, _mock_is_url_allowed, mock_request, status_code, payload, expected):
        from posthog.models.integration.gitlab import PastedTokenSource

        mock_request.return_value = MagicMock(status_code=status_code)
        mock_request.return_value.json.return_value = payload

        info = PastedTokenSource("https://gitlab.com", "token123").describe()

        actual = (info.expires_at.isoformat() if info.expires_at else None, info.missing_task_scopes) if info else None
        assert actual == expected

    @pytest.mark.parametrize(
        "method, kwargs, status_code",
        [
            ("list_projects", {}, 200),
            (
                "create_merge_request",
                {
                    "project_id": 7,
                    "source_branch": "posthog/fix-checkout",
                    "target_branch": "main",
                    "title": "Fix checkout",
                    "description": "Details",
                },
                201,
            ),
            ("get_merge_request", {"project_id": 7, "merge_request_iid": 5}, 200),
        ],
    )
    @patch("requests.request")
    @patch("posthog.models.integration.gitlab.is_url_allowed", return_value=(True, None))
    def test_project_and_merge_request_methods_reject_non_json_responses(
        self,
        _mock_is_url_allowed: MagicMock,
        mock_request: MagicMock,
        method: str,
        kwargs: dict[str, str | int],
        status_code: int,
    ) -> None:
        from posthog.models.integration import GitLabIntegration, GitLabIntegrationError

        integration = MagicMock(
            kind="gitlab",
            config={"hostname": "https://gitlab.example.com"},
            sensitive_config={"access_token": "glpat-not-a-real-token"},
        )
        mock_request.return_value = MagicMock(
            status_code=status_code,
            **{"json.side_effect": requests.JSONDecodeError("Expecting value", "", 0)},
        )

        with pytest.raises(GitLabIntegrationError, match="isn't JSON"):
            getattr(GitLabIntegration(integration), method)(**kwargs)

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
