from datetime import datetime

import pytest
from unittest.mock import Mock, patch

from parameterized import parameterized

from posthog.temporal.data_imports.sources.sentry.sentry import (
    SentryPaginator,
    _coerce_positive_int,
    _extract_rows,
    _normalize_api_base_url,
    _parse_next_link,
    get_resource,
    sentry_source,
    validate_credentials,
)


class TestSentryTransport:
    @staticmethod
    def _response(payload, status_code: int = 200, link_header: str = "") -> Mock:
        response = Mock()
        response.status_code = status_code
        response.headers = {"Link": link_header}
        response.json.return_value = payload
        response.text = "error"

        def _raise_for_status() -> None:
            if status_code >= 400:
                raise Exception(f"{status_code} client error")

        response.raise_for_status = _raise_for_status
        return response

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

    @parameterized.expand(
        [
            ("projects", "/organizations/acme/projects/", "id"),
            ("teams", "/organizations/acme/teams/", "id"),
            ("members", "/organizations/acme/members/", "id"),
            ("organization_users", "/organizations/acme/users/", "id"),
            ("releases", "/organizations/acme/releases/", "version"),
            ("environments", "/organizations/acme/environments/", "id"),
            ("monitors", "/organizations/acme/monitors/", "id"),
        ]
    )
    def test_get_resource_non_fanout_shape(self, endpoint, expected_path, expected_primary_key) -> None:
        resource = get_resource(
            endpoint=endpoint,
            organization_slug="acme",
            should_use_incremental_field=False,
        )

        assert resource["name"] == endpoint
        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["path"] == expected_path
        assert resource["primary_key"] == expected_primary_key
        assert resource["table_format"] == "delta"

    @parameterized.expand(
        [
            ("project_issues",),
            ("project_events",),
            ("project_users",),
            ("project_client_keys",),
            ("project_service_hooks",),
            ("issue_events",),
            ("issue_hashes",),
            ("issue_tag_values",),
        ]
    )
    def test_get_resource_rejects_fanout_endpoints(self, endpoint) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource(
                endpoint=endpoint,
                organization_slug="acme",
                should_use_incremental_field=False,
            )

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

    @parameterized.expand(
        [
            ("project_issues", "/projects/acme/web/issues/", {"id": "iss-1"}),
            ("project_events", "/projects/acme/web/events/", {"eventID": "evt-1"}),
            ("project_users", "/projects/acme/web/users/", {"id": "usr-1"}),
            ("project_client_keys", "/projects/acme/web/keys/", {"id": "key-1"}),
            ("project_service_hooks", "/projects/acme/web/hooks/", {"id": "hook-1"}),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.sentry.sentry.external_requests.get")
    def test_project_fanout_endpoint_row_format(self, endpoint, child_path, child_row, mock_get) -> None:
        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/projects/"):
                return self._response([{"id": "1", "slug": "web"}])
            if url.endswith(child_path):
                return self._response([child_row])
            return self._response([])

        mock_get.side_effect = side_effect

        response = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint=endpoint,
            team_id=123,
            job_id="job-id",
            max_projects_to_sync=10,
            max_pages_per_parent=5,
        )

        rows = list(response.items())
        assert len(rows) == 1
        row = rows[0]
        assert isinstance(row, dict)
        assert row["organization_slug"] == "acme"
        assert row["project_slug"] == "web"
        assert row["project_id"] == "1"
        assert row["source_endpoint"] == endpoint

    @parameterized.expand(
        [
            ("issue_events", "/issues/100/events/", [{"eventID": "evt-1", "message": "boom"}], None),
            ("issue_hashes", "/issues/100/hashes/", [{"id": "hash-1", "hash": "abc"}], None),
            (
                "issue_tag_values",
                "/issues/100/tags/browser/values/",
                [{"value": "Chrome", "timesSeen": 1}],
                [{"key": "browser"}],
            ),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.sentry.sentry.external_requests.get")
    def test_issue_fanout_endpoint_row_format(self, endpoint, child_path, child_rows, tags_rows, mock_get) -> None:
        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/"):
                return self._response([{"id": "100"}])
            if tags_rows is not None and url.endswith("/issues/100/tags/"):
                return self._response(tags_rows)
            if url.endswith(child_path):
                return self._response(child_rows)
            return self._response([])

        mock_get.side_effect = side_effect

        response = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint=endpoint,
            team_id=123,
            job_id="job-id",
            max_issues_to_fanout=10,
            max_pages_per_parent=5,
        )

        rows = list(response.items())
        assert len(rows) == 1
        row = rows[0]
        assert isinstance(row, dict)
        assert row["organization_slug"] == "acme"
        assert row["issue_id"] == "100"
        assert row["source_endpoint"] == endpoint
        if endpoint == "issue_tag_values":
            assert row["tag_key"] == "browser"


class TestHelpers:
    @parameterized.expand(
        [
            ("has_next", '<https://a.io/next>; rel="next"; results="true"', "https://a.io/next"),
            ("no_results", '<https://a.io/next>; rel="next"; results="false"', None),
            ("empty", "", None),
            ("only_prev", '<https://a.io/prev>; rel="previous"; results="true"', None),
        ]
    )
    def test_parse_next_link(self, _name, link_header, expected) -> None:
        assert _parse_next_link(link_header) == expected

    @parameterized.expand(
        [
            ("list_payload", [{"id": 1}, {"id": 2}], 2),
            ("dict_with_data", {"data": [{"id": 1}]}, 1),
            ("bare_dict", {"id": 1}, 1),
            ("empty_list", [], 0),
            ("non_dict_items", [1, "str", None], 0),
        ]
    )
    def test_extract_rows(self, _name, payload, expected_count) -> None:
        rows = _extract_rows(payload)
        assert len(rows) == expected_count
        assert all(isinstance(r, dict) for r in rows)

    @parameterized.expand(
        [
            ("none_returns_fallback", None, 42, 42),
            ("zero_returns_fallback", 0, 42, 42),
            ("negative_returns_fallback", -1, 42, 42),
            ("positive_returns_value", 10, 42, 10),
        ]
    )
    def test_coerce_positive_int(self, _name, value, fallback, expected) -> None:
        assert _coerce_positive_int(value, fallback) == expected
