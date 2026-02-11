from datetime import UTC, date, datetime
from typing import Any

from unittest import mock

import requests
from parameterized import parameterized

from posthog.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from posthog.temporal.data_imports.sources.github.github import (
    GithubPaginator,
    _flatten_commit,
    _flatten_stargazer,
    _format_incremental_value,
    _is_issue_not_pr,
    get_resource,
    validate_credentials,
)


def _endpoint_params(resource: EndpointResource) -> dict[str, Any]:
    endpoint = resource.get("endpoint")
    assert isinstance(endpoint, dict)
    params = endpoint.get("params")
    assert isinstance(params, dict)
    return params


def _endpoint_path(resource: EndpointResource) -> str:
    endpoint = resource.get("endpoint")
    assert isinstance(endpoint, dict)
    path = endpoint.get("path")
    assert isinstance(path, str)
    return path


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("datetime", datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC), "2026-01-15T10:00:00+00:00"),
            ("date", date(2026, 1, 15), "2026-01-15T00:00:00"),
            ("string_passthrough", "2026-01-15T10:00:00Z", "2026-01-15T10:00:00Z"),
            ("integer_passthrough", 1737100800, "1737100800"),
        ]
    )
    def test_formats_value(self, _name, value, expected):
        assert _format_incremental_value(value) == expected


class TestGetResource:
    def test_issues_full_refresh(self):
        resource = get_resource("issues", "owner/repo", should_use_incremental_field=False)
        params = _endpoint_params(resource)

        assert resource["name"] == "issues"
        assert resource["primary_key"] == "id"
        assert resource["write_disposition"] == "replace"
        assert _endpoint_path(resource) == "/repos/owner/repo/issues"
        assert params["state"] == "all"
        assert params["per_page"] == 100
        assert "since" not in params

    def test_issues_incremental_with_since(self):
        last_value = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
        resource = get_resource(
            "issues",
            "owner/repo",
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )
        params = _endpoint_params(resource)

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        assert params["since"] == "2026-01-15T10:00:00+00:00"
        assert params["sort"] == "updated"
        assert params["direction"] == "asc"

    def test_commits_incremental_with_since(self):
        last_value = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
        resource = get_resource(
            "commits",
            "owner/repo",
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )
        params = _endpoint_params(resource)

        assert resource["primary_key"] == "sha"
        assert params["since"] == "2026-01-15T10:00:00+00:00"
        assert params["sort"] == "created"
        assert params["direction"] == "desc"

    @parameterized.expand(
        [
            ("updated_at", "updated_at", "updated"),
            ("created_at", "created_at", "created"),
            ("default_to_updated", None, "updated"),
        ]
    )
    def test_pull_requests_incremental_sort_with_cutoff(self, _name, incremental_field, expected_sort):
        last_value = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
        resource = get_resource(
            "pull_requests",
            "owner/repo",
            should_use_incremental_field=True,
            incremental_field=incremental_field,
            db_incremental_field_last_value=last_value,
        )
        params = _endpoint_params(resource)

        assert params["sort"] == expected_sort
        assert params["direction"] == "desc"
        assert "since" not in params

    def test_pull_requests_incremental_created_asc_without_cutoff(self):
        resource = get_resource(
            "pull_requests",
            "owner/repo",
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        params = _endpoint_params(resource)

        assert params["sort"] == "created"
        assert params["direction"] == "asc"

    def test_pull_requests_full_refresh_created_asc(self):
        resource = get_resource("pull_requests", "owner/repo", should_use_incremental_field=False)
        params = _endpoint_params(resource)

        assert params["sort"] == "created"
        assert params["direction"] == "asc"

    def test_issues_incremental_no_since_without_last_value(self):
        resource = get_resource(
            "issues",
            "owner/repo",
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        params = _endpoint_params(resource)

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        assert "since" not in params
        assert params["sort"] == "created"
        assert params["direction"] == "asc"


class TestGithubPaginator:
    def _make_response(self, link_header: str = "") -> mock.MagicMock:
        response = mock.MagicMock()
        response.headers = {"Link": link_header} if link_header else {}
        return response

    def test_no_link_header(self):
        paginator = GithubPaginator()
        paginator.update_state(self._make_response(), data=[{"id": 1}])

        assert paginator.has_next_page is False

    def test_next_page_from_link_header(self):
        link = '<https://api.github.com/repos/owner/repo/issues?page=2>; rel="next", <https://api.github.com/repos/owner/repo/issues?page=5>; rel="last"'
        paginator = GithubPaginator()
        paginator.update_state(self._make_response(link), data=[{"id": 1}])

        assert paginator.has_next_page is True
        assert paginator._next_url == "https://api.github.com/repos/owner/repo/issues?page=2"

    def test_no_next_rel_in_link_header(self):
        link = '<https://api.github.com/repos/owner/repo/issues?page=1>; rel="prev"'
        paginator = GithubPaginator()
        paginator.update_state(self._make_response(link), data=[{"id": 1}])

        assert paginator.has_next_page is False

    def test_desc_sort_stops_on_old_records(self):
        cutoff = datetime(2026, 1, 20, 0, 0, 0, tzinfo=UTC)
        link = '<https://api.github.com/next>; rel="next"'
        paginator = GithubPaginator(
            incremental_field="updated_at",
            db_incremental_field_last_value=cutoff,
            sort_mode="desc",
        )

        data = [
            {"updated_at": "2026-01-25T10:00:00Z"},
            {"updated_at": "2026-01-19T10:00:00Z"},  # older than cutoff
        ]
        paginator.update_state(self._make_response(link), data=data)

        assert paginator.has_next_page is False

    def test_desc_sort_continues_when_all_newer(self):
        cutoff = datetime(2026, 1, 10, 0, 0, 0, tzinfo=UTC)
        link = '<https://api.github.com/next>; rel="next"'
        paginator = GithubPaginator(
            incremental_field="updated_at",
            db_incremental_field_last_value=cutoff,
            sort_mode="desc",
        )

        data = [
            {"updated_at": "2026-01-25T10:00:00Z"},
            {"updated_at": "2026-01-15T10:00:00Z"},
        ]
        paginator.update_state(self._make_response(link), data=data)

        assert paginator.has_next_page is True

    def test_asc_sort_ignores_cutoff(self):
        cutoff = datetime(2026, 1, 20, 0, 0, 0, tzinfo=UTC)
        link = '<https://api.github.com/next>; rel="next"'
        paginator = GithubPaginator(
            incremental_field="updated_at",
            db_incremental_field_last_value=cutoff,
            sort_mode="asc",
        )

        data = [{"updated_at": "2026-01-10T10:00:00Z"}]
        paginator.update_state(self._make_response(link), data=data)

        assert paginator.has_next_page is True

    def test_desc_sort_no_cutoff_continues(self):
        link = '<https://api.github.com/next>; rel="next"'
        paginator = GithubPaginator(
            incremental_field="updated_at",
            db_incremental_field_last_value=None,
            sort_mode="desc",
        )

        data = [{"updated_at": "2026-01-10T10:00:00Z"}]
        paginator.update_state(self._make_response(link), data=data)

        assert paginator.has_next_page is True

    def test_update_request_sets_next_url(self):
        link = '<https://api.github.com/repos/owner/repo/issues?page=2>; rel="next"'
        paginator = GithubPaginator()
        paginator.update_state(self._make_response(link), data=[{"id": 1}])

        request = mock.MagicMock()
        request.params = {"per_page": 100}
        paginator.update_request(request)

        assert request.url == "https://api.github.com/repos/owner/repo/issues?page=2"
        assert request.params == {}


class TestIsOlderThanCutoff:
    @parameterized.expand(
        [
            ("z_suffix_older", "2026-01-15T10:00:00Z", True),
            ("offset_older", "2026-01-15T10:00:00+00:00", True),
            ("equal_to_cutoff", "2026-01-20T00:00:00Z", True),
            ("newer_than_cutoff", "2026-01-25T10:00:00Z", False),
            ("none_value", None, False),
            ("invalid_string", "not-a-date", False),
        ]
    )
    def test_string_comparison(self, _name, value, expected):
        cutoff = datetime(2026, 1, 20, 0, 0, 0, tzinfo=UTC)
        paginator = GithubPaginator(db_incremental_field_last_value=cutoff)
        assert paginator._is_older_than_cutoff(value) == expected

    def test_datetime_comparison(self):
        cutoff = datetime(2026, 1, 20, 0, 0, 0, tzinfo=UTC)
        paginator = GithubPaginator(db_incremental_field_last_value=cutoff)

        assert paginator._is_older_than_cutoff(datetime(2026, 1, 15, 0, 0, 0, tzinfo=UTC)) is True
        assert paginator._is_older_than_cutoff(datetime(2026, 1, 25, 0, 0, 0, tzinfo=UTC)) is False

    def test_none_cutoff(self):
        paginator = GithubPaginator(db_incremental_field_last_value=None)
        assert paginator._is_older_than_cutoff("2026-01-15T10:00:00Z") is False


class TestFlattenCommit:
    def test_flattens_nested_commit_data(self):
        item = {
            "sha": "abc123",
            "commit": {
                "message": "Fix bug",
                "author": {
                    "name": "Alice",
                    "email": "alice@example.com",
                    "date": "2026-01-10T10:00:00Z",
                },
                "committer": {
                    "name": "Bob",
                    "email": "bob@example.com",
                    "date": "2026-01-10T11:00:00Z",
                },
            },
            "author": {"id": 100, "login": "alice"},
            "committer": {"id": 101, "login": "bob"},
        }

        result = _flatten_commit(item)

        assert result["message"] == "Fix bug"
        assert result["author_name"] == "Alice"
        assert result["author_email"] == "alice@example.com"
        assert result["created_at"] == "2026-01-10T10:00:00Z"
        assert result["committer_name"] == "Bob"
        assert result["committer_email"] == "bob@example.com"
        assert result["committed_at"] == "2026-01-10T11:00:00Z"
        assert result["author_id"] == 100
        assert result["author_login"] == "alice"
        assert result["committer_id"] == 101
        assert result["committer_login"] == "bob"

    def test_handles_missing_nested_data(self):
        item = {"sha": "abc123"}
        result = _flatten_commit(item)

        assert result == {"sha": "abc123"}
        assert "message" not in result
        assert "author_name" not in result


class TestFlattenStargazer:
    def test_flattens_user_data(self):
        item = {
            "starred_at": "2026-01-10T10:00:00Z",
            "user": {
                "id": 100,
                "login": "alice",
                "avatar_url": "https://avatars.githubusercontent.com/u/100",
                "type": "User",
            },
        }

        result = _flatten_stargazer(item)

        assert result["id"] == 100
        assert result["login"] == "alice"
        assert result["avatar_url"] == "https://avatars.githubusercontent.com/u/100"
        assert result["type"] == "User"
        assert result["starred_at"] == "2026-01-10T10:00:00Z"
        assert "user" not in result

    def test_handles_missing_user(self):
        item = {"starred_at": "2026-01-10T10:00:00Z"}
        result = _flatten_stargazer(item)

        assert result == {"starred_at": "2026-01-10T10:00:00Z"}


class TestIsIssueNotPr:
    @parameterized.expand(
        [
            ("regular_issue", {"id": 1, "title": "Bug"}, True),
            ("pr_present", {"id": 2, "pull_request": {"url": "..."}}, False),
            ("pr_null", {"id": 3, "pull_request": None}, True),
        ]
    )
    def test_filters_correctly(self, _name, item, expected):
        assert _is_issue_not_pr(item) == expected


class TestValidateCredentials:
    def test_valid_credentials(self):
        with mock.patch("posthog.temporal.data_imports.sources.github.github.requests.get") as mock_get:
            mock_get.return_value = mock.MagicMock(status_code=200)
            valid, error = validate_credentials("token", "owner/repo")

        assert valid is True
        assert error is None

    @parameterized.expand(
        [
            ("unauthorized", 401, "Invalid personal access token"),
            ("not_found", 404, "Repository 'owner/repo' not found or not accessible"),
        ]
    )
    def test_error_status_codes(self, _name, status_code, expected_message):
        with mock.patch("posthog.temporal.data_imports.sources.github.github.requests.get") as mock_get:
            mock_get.return_value = mock.MagicMock(status_code=status_code)
            valid, error = validate_credentials("token", "owner/repo")

        assert valid is False
        assert error == expected_message

    def test_json_error_response(self):
        with mock.patch("posthog.temporal.data_imports.sources.github.github.requests.get") as mock_get:
            mock_response = mock.MagicMock(status_code=403)
            mock_response.json.return_value = {"message": "API rate limit exceeded"}
            mock_get.return_value = mock_response
            valid, error = validate_credentials("token", "owner/repo")

        assert valid is False
        assert error == "API rate limit exceeded"

    def test_request_exception(self):
        with mock.patch("posthog.temporal.data_imports.sources.github.github.requests.get") as mock_get:
            mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")
            valid, error = validate_credentials("token", "owner/repo")

        assert valid is False
        assert error is not None
        assert "Connection refused" in error

    def test_sends_correct_headers(self):
        with mock.patch("posthog.temporal.data_imports.sources.github.github.requests.get") as mock_get:
            mock_get.return_value = mock.MagicMock(status_code=200)
            validate_credentials("my-token", "owner/repo")

        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args
        assert call_kwargs is not None
        headers = call_kwargs.kwargs["headers"]
        assert headers["Authorization"] == "Bearer my-token"
        assert headers["X-GitHub-Api-Version"] == "2022-11-28"
