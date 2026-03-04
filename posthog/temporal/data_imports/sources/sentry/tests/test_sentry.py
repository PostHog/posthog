from datetime import datetime

from unittest.mock import Mock, patch

from parameterized import parameterized

from posthog.temporal.data_imports.sources.sentry.sentry import (
    SentryPaginator,
    _normalize_api_base_url,
    get_resource,
    sentry_source,
    validate_credentials,
)


class TestSentryTransport:
    def test_normalize_api_base_url(self) -> None:
        assert _normalize_api_base_url(None) == "https://sentry.io"
        assert _normalize_api_base_url("https://us.sentry.io/") == "https://us.sentry.io"

    @parameterized.expand(
        [
            (
                "has_next",
                '<https://sentry.io/api/0/organizations/acme/issues/?cursor=0:100:0>; rel="next"; results="true"',
                True,
            ),
            (
                "no_more_results",
                '<https://sentry.io/api/0/organizations/acme/issues/?cursor=0:100:0>; rel="next"; results="false"',
                False,
            ),
            ("missing_link", "", False),
        ]
    )
    def test_paginator_update_state(self, _name, link_header, expected_has_next) -> None:
        paginator = SentryPaginator()
        response = Mock()
        response.headers = {"Link": link_header}

        paginator.update_state(response)

        assert paginator.has_next_page == expected_has_next

    def test_paginator_update_request_sets_next_url(self) -> None:
        paginator = SentryPaginator()
        response = Mock()
        response.headers = {
            "Link": '<https://sentry.io/api/0/organizations/acme/issues/?cursor=0:100:0>; rel="next"; results="true"'
        }
        paginator.update_state(response)

        request = Mock()
        request.url = "/api/0/organizations/acme/issues/"
        request.params = {"limit": 100}
        paginator.update_request(request)

        assert request.url == "https://sentry.io/api/0/organizations/acme/issues/?cursor=0:100:0"
        assert request.params == {}

    def test_get_resource_incremental_issues(self) -> None:
        resource = get_resource(
            endpoint="issues",
            organization_slug="acme",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2025, 1, 1, 10, 30, 0),
            incremental_field="lastSeen",
        )

        assert resource["name"] == "issues"
        assert resource["write_disposition"]["disposition"] == "merge"
        assert resource["endpoint"]["params"]["query"] == ""
        assert resource["endpoint"]["params"]["sort"] == "date"
        assert "start" in resource["endpoint"]["params"]

    def test_get_resource_projects_full_refresh(self) -> None:
        resource = get_resource(
            endpoint="projects",
            organization_slug="acme",
            should_use_incremental_field=False,
        )

        assert resource["name"] == "projects"
        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["path"] == "/organizations/acme/projects/"

    @parameterized.expand(
        [
            ("ok", 200, (True, None)),
            ("unauthorized", 401, (False, "Invalid Sentry auth token")),
            ("forbidden", 403, (False, "Sentry token is missing required scopes (org:read)")),
            ("not_found", 404, (False, "Sentry organization 'acme' not found")),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.sentry.sentry.external_requests.get")
    def test_validate_credentials(self, _name, status_code, expected, mock_get) -> None:
        response = Mock()
        response.status_code = status_code
        response.text = "error"
        response.json.return_value = {"detail": "error"}
        mock_get.return_value = response

        result = validate_credentials(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
        )

        assert result == expected

    @patch("posthog.temporal.data_imports.sources.sentry.sentry.rest_api_resources")
    def test_sentry_source_builds_response(self, mock_rest_api_resources) -> None:
        mock_resource = Mock()
        mock_rest_api_resources.return_value = [mock_resource]

        response = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issues",
            team_id=123,
            job_id="job-id",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2025, 1, 1, 10, 30, 0),
            incremental_field="lastSeen",
        )

        assert response.name == "issues"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
