import dataclasses
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from unittest import mock

import requests
from parameterized import parameterized

from posthog.temporal.data_imports.sources.github.github import (
    GithubResumeConfig,
    _build_initial_params,
    _build_initial_url,
    _flatten_commit,
    _flatten_stargazer,
    _format_incremental_value,
    _is_issue_not_pr,
    _is_older_than_cutoff,
    _iter_jobs_for_run,
    _iter_pages,
    _parse_next_url,
    _should_stop_desc,
    get_rows,
    github_source,
    validate_credentials,
)
from posthog.temporal.data_imports.sources.github.settings import GITHUB_ENDPOINTS


def _make_response(status: int = 200, body: Any = None, link: str = "") -> mock.Mock:
    resp = mock.Mock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = body if body is not None else []
    resp.headers = {"Link": link} if link else {}
    return resp


def _make_manager(*, can_resume: bool = False, resume_state: GithubResumeConfig | None = None) -> mock.Mock:
    manager = mock.Mock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = resume_state
    manager.save_state = mock.Mock()
    return manager


class _ImmediateBatcher:
    """Test double for Batcher that emits every batched item as its own chunk."""

    def __init__(self) -> None:
        self._item: Any = None

    def batch(self, item: Any) -> None:
        self._item = item

    def should_yield(self, include_incomplete_chunk: bool = False) -> bool:
        return self._item is not None

    def get_table(self) -> Any:
        item = self._item
        self._item = None
        return item


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("datetime", datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC), "2026-01-15T10:00:00+00:00"),
            ("date", date(2026, 1, 15), "2026-01-15T00:00:00"),
            ("string_passthrough", "2026-01-15T10:00:00Z", "2026-01-15T10:00:00Z"),
            ("integer_passthrough", 1737100800, "1737100800"),
        ]
    )
    def test_formats_value(self, _name: str, value: Any, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestBuildInitialParams:
    def test_issues_full_refresh_defaults(self) -> None:
        params = _build_initial_params(
            GITHUB_ENDPOINTS["issues"],
            "issues",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )

        assert params["sort"] == "created"
        assert params["direction"] == "asc"
        assert params["state"] == "all"
        assert params["per_page"] == 100
        assert "since" not in params

    def test_issues_incremental_with_since(self) -> None:
        last_value = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
        params = _build_initial_params(
            GITHUB_ENDPOINTS["issues"],
            "issues",
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
            incremental_field="updated_at",
        )

        assert params["since"] == "2026-01-15T10:00:00+00:00"
        assert params["sort"] == "updated"
        assert params["direction"] == "asc"

    def test_commits_incremental_desc(self) -> None:
        last_value = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
        params = _build_initial_params(
            GITHUB_ENDPOINTS["commits"],
            "commits",
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
            incremental_field="created_at",
        )

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
    def test_pull_requests_incremental_sort_with_cutoff(
        self, _name: str, incremental_field: str | None, expected_sort: str
    ) -> None:
        last_value = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
        params = _build_initial_params(
            GITHUB_ENDPOINTS["pull_requests"],
            "pull_requests",
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
            incremental_field=incremental_field,
        )

        assert params["sort"] == expected_sort
        assert params["direction"] == "desc"
        assert "since" not in params  # pull_requests does not support 'since'

    def test_issues_incremental_no_since_without_last_value(self) -> None:
        params = _build_initial_params(
            GITHUB_ENDPOINTS["issues"],
            "issues",
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )

        assert "since" not in params
        assert params["sort"] == "created"
        assert params["direction"] == "asc"

    @parameterized.expand(
        [
            ("full_refresh", False, None),
            ("incremental_first_sync", True, None),
            ("incremental_with_cutoff", True, datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)),
        ]
    )
    def test_workflow_runs_always_minimal_params(
        self, _name: str, should_use_incremental_field: bool, last_value: Any
    ) -> None:
        params = _build_initial_params(
            GITHUB_ENDPOINTS["workflow_runs"],
            "workflow_runs",
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
            incremental_field="created_at",
        )

        # workflow_runs is always a plain paged read: no state/sort/direction,
        # no `since`, and crucially no `created` filter (the filter caps results
        # at 1,000). Incremental bounding happens client-side via desc
        # early-stop in get_rows, so the request never changes shape.
        assert params == {"per_page": 100}


class TestBuildInitialUrl:
    def test_with_params(self) -> None:
        url = _build_initial_url(GITHUB_ENDPOINTS["issues"], "owner/repo", {"per_page": 100, "state": "all"})
        assert url == "https://api.github.com/repos/owner/repo/issues?per_page=100&state=all"

    def test_no_params(self) -> None:
        url = _build_initial_url(GITHUB_ENDPOINTS["issues"], "owner/repo", {})
        assert url == "https://api.github.com/repos/owner/repo/issues"


class TestParseNextUrl:
    @parameterized.expand(
        [
            ("empty", "", None),
            (
                "next_and_last",
                '<https://api.github.com/x?page=2>; rel="next", <https://api.github.com/x?page=5>; rel="last"',
                "https://api.github.com/x?page=2",
            ),
            ("only_last", '<https://api.github.com/x?page=5>; rel="last"', None),
            (
                "prev_and_next",
                '<https://api.github.com/x?page=1>; rel="prev", <https://api.github.com/x?page=3>; rel="next"',
                "https://api.github.com/x?page=3",
            ),
        ]
    )
    def test_parse(self, _name: str, header: str, expected: str | None) -> None:
        assert _parse_next_url(header) == expected


class TestIsOlderThanCutoff:
    @parameterized.expand(
        [
            ("z_suffix_older", "2026-01-15T10:00:00Z", True),
            ("offset_older", "2026-01-15T10:00:00+00:00", True),
            ("equal_to_cutoff", "2026-01-20T00:00:00+00:00", True),
            ("newer_than_cutoff", "2026-01-25T10:00:00Z", False),
            ("none_value", None, False),
            ("invalid_string", "not-a-date", False),
        ]
    )
    def test_string_comparison(self, _name: str, value: Any, expected: bool) -> None:
        cutoff = datetime(2026, 1, 20, 0, 0, 0, tzinfo=UTC)
        assert _is_older_than_cutoff(value, cutoff) is expected

    def test_datetime_comparison(self) -> None:
        cutoff = datetime(2026, 1, 20, 0, 0, 0, tzinfo=UTC)
        assert _is_older_than_cutoff(datetime(2026, 1, 15, 0, 0, 0, tzinfo=UTC), cutoff) is True
        assert _is_older_than_cutoff(datetime(2026, 1, 25, 0, 0, 0, tzinfo=UTC), cutoff) is False

    @parameterized.expand(
        [
            # aware value vs naive cutoff — naive treated as UTC, older wins
            ("aware_str_naive_cutoff_older", "2026-01-15T10:00:00Z", datetime(2026, 1, 20, 0, 0, 0), True),
            ("aware_str_naive_cutoff_newer", "2026-01-25T10:00:00Z", datetime(2026, 1, 20, 0, 0, 0), False),
            # naive datetime value vs aware cutoff — naive treated as UTC
            (
                "naive_datetime_aware_cutoff_older",
                datetime(2026, 1, 15, 0, 0, 0),
                datetime(2026, 1, 20, 0, 0, 0, tzinfo=UTC),
                True,
            ),
            # naive string vs aware cutoff — naive treated as UTC
            ("naive_str_aware_cutoff_older", "2026-01-15T10:00:00", datetime(2026, 1, 20, 0, 0, 0, tzinfo=UTC), True),
        ]
    )
    def test_mixed_aware_and_naive(self, _name: str, value: Any, cutoff: datetime, expected: bool) -> None:
        """Mixing aware and naive datetimes must not raise — naive is treated as UTC."""
        assert _is_older_than_cutoff(value, cutoff) is expected


class TestShouldStopDesc:
    def test_asc_mode_never_stops(self) -> None:
        assert (
            _should_stop_desc(
                data=[{"updated_at": "2000-01-01T00:00:00Z"}],
                sort_mode="asc",
                incremental_field="updated_at",
                cutoff=datetime(2026, 3, 4, tzinfo=UTC),
            )
            is False
        )

    def test_desc_stops_on_old_record(self) -> None:
        assert (
            _should_stop_desc(
                data=[
                    {"updated_at": "2026-05-01T00:00:00Z"},
                    {"updated_at": "2025-01-01T00:00:00Z"},
                ],
                sort_mode="desc",
                incremental_field="updated_at",
                cutoff=datetime(2026, 3, 4, tzinfo=UTC),
            )
            is True
        )

    def test_desc_continues_when_all_newer(self) -> None:
        assert (
            _should_stop_desc(
                data=[{"updated_at": "2026-05-01T00:00:00Z"}],
                sort_mode="desc",
                incremental_field="updated_at",
                cutoff=datetime(2026, 3, 4, tzinfo=UTC),
            )
            is False
        )

    def test_desc_no_cutoff_continues(self) -> None:
        assert (
            _should_stop_desc(
                data=[{"updated_at": "2026-05-01T00:00:00Z"}],
                sort_mode="desc",
                incremental_field="updated_at",
                cutoff=None,
            )
            is False
        )


class TestFlattenCommit:
    def test_flattens_nested_commit_data(self) -> None:
        item = {
            "sha": "abc123",
            "commit": {
                "message": "Fix bug",
                "author": {"name": "Alice", "email": "alice@example.com", "date": "2026-01-10T10:00:00Z"},
                "committer": {"name": "Bob", "email": "bob@example.com", "date": "2026-01-10T11:00:00Z"},
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

    def test_handles_missing_nested_data(self) -> None:
        item = {"sha": "abc123"}
        result = _flatten_commit(item)

        assert result == {"sha": "abc123"}


class TestFlattenStargazer:
    def test_flattens_user_data(self) -> None:
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

    def test_handles_missing_user(self) -> None:
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
    def test_filters_correctly(self, _name: str, item: dict[str, Any], expected: bool) -> None:
        assert _is_issue_not_pr(item) == expected


class TestValidateCredentials:
    def test_valid_credentials(self) -> None:
        with mock.patch("posthog.temporal.data_imports.sources.github.github.make_tracked_session") as mock_get:
            mock_get.return_value.get.return_value = mock.MagicMock(status_code=200)
            valid, error = validate_credentials("token", "owner/repo")

        assert valid is True
        assert error is None

    @parameterized.expand(
        [
            ("unauthorized", 401, "Invalid personal access token"),
            ("not_found", 404, "Repository 'owner/repo' not found or not accessible"),
        ]
    )
    def test_error_status_codes(self, _name: str, status_code: int, expected_message: str) -> None:
        with mock.patch("posthog.temporal.data_imports.sources.github.github.make_tracked_session") as mock_get:
            mock_get.return_value.get.return_value = mock.MagicMock(status_code=status_code)
            valid, error = validate_credentials("token", "owner/repo")

        assert valid is False
        assert error == expected_message

    def test_json_error_response(self) -> None:
        with mock.patch("posthog.temporal.data_imports.sources.github.github.make_tracked_session") as mock_get:
            mock_response = mock.MagicMock(status_code=403)
            mock_response.json.return_value = {"message": "API rate limit exceeded"}
            mock_get.return_value.get.return_value = mock_response
            valid, error = validate_credentials("token", "owner/repo")

        assert valid is False
        assert error == "API rate limit exceeded"

    def test_request_exception(self) -> None:
        with mock.patch("posthog.temporal.data_imports.sources.github.github.make_tracked_session") as mock_get:
            mock_get.return_value.get.side_effect = requests.exceptions.ConnectionError("Connection refused")
            valid, error = validate_credentials("token", "owner/repo")

        assert valid is False
        assert error is not None
        assert "Connection refused" in error

    def test_sends_correct_headers(self) -> None:
        with mock.patch("posthog.temporal.data_imports.sources.github.github.make_tracked_session") as mock_get:
            mock_get.return_value.get.return_value = mock.MagicMock(status_code=200)
            validate_credentials("my-token", "owner/repo")

        mock_get.return_value.get.assert_called_once()
        call_kwargs = mock_get.return_value.get.call_args
        assert call_kwargs is not None
        headers = call_kwargs.kwargs["headers"]
        assert headers["Authorization"] == "Bearer my-token"
        assert headers["X-GitHub-Api-Version"] == "2022-11-28"


class TestGithubSourceSortMode:
    """SourceResponse.sort_mode must match the actual API request direction."""

    def _make_source(
        self,
        endpoint: str,
        should_use_incremental_field: bool,
        db_incremental_field_last_value: Any = None,
    ) -> Any:
        return github_source(
            personal_access_token="token",
            repository="owner/repo",
            endpoint=endpoint,
            logger=mock.Mock(),
            resumable_source_manager=_make_manager(),
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )

    @parameterized.expand(
        [
            ("pull_requests_first_sync_no_cutoff", "pull_requests", True, None, "asc"),
            ("pull_requests_full_refresh", "pull_requests", False, None, "asc"),
            (
                "pull_requests_incremental_with_cutoff",
                "pull_requests",
                True,
                datetime(2026, 1, 15, tzinfo=UTC),
                "desc",
            ),
            ("commits_first_sync_no_cutoff", "commits", True, None, "asc"),
            (
                "commits_incremental_with_cutoff",
                "commits",
                True,
                datetime(2026, 1, 15, tzinfo=UTC),
                "desc",
            ),
            ("issues_always_asc", "issues", True, datetime(2026, 1, 15, tzinfo=UTC), "asc"),
            # workflow_runs always emits newest-first (the API ignores sort), so
            # sort_mode must be desc even on the first sync / full refresh —
            # never the asc default that other endpoints use before a cutoff.
            ("workflow_runs_full_refresh", "workflow_runs", False, None, "desc"),
            ("workflow_runs_first_sync_no_cutoff", "workflow_runs", True, None, "desc"),
            (
                "workflow_runs_incremental_with_cutoff",
                "workflow_runs",
                True,
                datetime(2026, 1, 15, tzinfo=UTC),
                "desc",
            ),
            # workflow_jobs fans out over workflow_runs newest-first, so it emits
            # desc on every sync — same as its parent.
            ("workflow_jobs_full_refresh", "workflow_jobs", False, None, "desc"),
            ("workflow_jobs_first_sync_no_cutoff", "workflow_jobs", True, None, "desc"),
            (
                "workflow_jobs_incremental_with_cutoff",
                "workflow_jobs",
                True,
                datetime(2026, 1, 15, tzinfo=UTC),
                "desc",
            ),
        ]
    )
    def test_sort_mode(
        self,
        _name: str,
        endpoint: str,
        incremental: bool,
        cutoff: Any,
        expected_sort_mode: str,
    ) -> None:
        response = self._make_source(endpoint, incremental, cutoff)
        assert response.sort_mode == expected_sort_mode


class TestGetRowsResume:
    """Integration tests for the fresh-run and resume flows in get_rows."""

    def _patch_batcher(self) -> Any:
        return mock.patch(
            "posthog.temporal.data_imports.sources.github.github.Batcher",
            autospec=False,
            side_effect=lambda logger, chunk_size, chunk_size_bytes: _ImmediateBatcher(),
        )

    def test_fresh_run_saves_current_page_url_after_batch(self) -> None:
        """save_state checkpoints the *current* page URL so resume re-fetches it;
        duplicates are deduped via primary_keys merge semantics."""
        manager = _make_manager(can_resume=False)
        page1 = [{"id": 1, "updated_at": "2026-01-01T00:00:00Z"}]
        page2 = [{"id": 2, "updated_at": "2026-01-02T00:00:00Z"}]
        link_page1 = '<https://api.github.com/repos/owner/repo/releases?page=2>; rel="next"'
        responses = [
            _make_response(body=page1, link=link_page1),
            _make_response(body=page2, link=""),
        ]

        with (
            self._patch_batcher(),
            mock.patch(
                "posthog.temporal.data_imports.sources.github.github.make_tracked_session",
            ) as mock_get,
        ):
            mock_get.return_value.get.side_effect = responses
            list(
                get_rows(
                    personal_access_token="tok",
                    repository="owner/repo",
                    endpoint="releases",
                    logger=mock.Mock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=False,
                )
            )

        first_url = mock_get.return_value.get.call_args_list[0].args[0]
        assert first_url.startswith("https://api.github.com/repos/owner/repo/releases")
        manager.load_state.assert_not_called()

        # Two yields (one per page) → two checkpoints, each pointing at the page
        # whose yield just completed.
        assert manager.save_state.call_count == 2
        saved_urls = [call.args[0].next_url for call in manager.save_state.call_args_list]
        assert saved_urls[0] == first_url
        assert saved_urls[1] == "https://api.github.com/repos/owner/repo/releases?page=2"

    def test_resume_uses_saved_url(self) -> None:
        saved_url = "https://api.github.com/repos/owner/repo/releases?page=4"
        manager = _make_manager(can_resume=True, resume_state=GithubResumeConfig(next_url=saved_url))
        responses = [_make_response(body=[{"id": 42, "updated_at": "2026-01-01T00:00:00Z"}], link="")]

        with (
            self._patch_batcher(),
            mock.patch(
                "posthog.temporal.data_imports.sources.github.github.make_tracked_session",
            ) as mock_get,
        ):
            mock_get.return_value.get.side_effect = responses
            list(
                get_rows(
                    personal_access_token="tok",
                    repository="owner/repo",
                    endpoint="releases",
                    logger=mock.Mock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=False,
                )
            )

        assert mock_get.return_value.get.call_args_list[0].args[0] == saved_url
        manager.load_state.assert_called_once()

    def test_empty_first_page_ends_loop(self) -> None:
        manager = _make_manager(can_resume=False)
        with (
            self._patch_batcher(),
            mock.patch(
                "posthog.temporal.data_imports.sources.github.github.make_tracked_session",
            ) as mock_get,
        ):
            mock_get.return_value.get.side_effect = [_make_response(body=[], link="")]
            rows = list(
                get_rows(
                    personal_access_token="tok",
                    repository="owner/repo",
                    endpoint="releases",
                    logger=mock.Mock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=False,
                )
            )

        assert rows == []
        manager.save_state.assert_not_called()

    def test_single_page_saves_current_page_url(self) -> None:
        """A single-page response still saves state for the page we yielded,
        so a restart right after the yield would re-fetch and dedupe."""
        manager = _make_manager(can_resume=False)
        with (
            self._patch_batcher(),
            mock.patch(
                "posthog.temporal.data_imports.sources.github.github.make_tracked_session",
            ) as mock_get,
        ):
            mock_get.return_value.get.side_effect = [_make_response(body=[{"id": 1}], link="")]
            list(
                get_rows(
                    personal_access_token="tok",
                    repository="owner/repo",
                    endpoint="releases",
                    logger=mock.Mock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=False,
                )
            )

        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args.args[0]
        assert saved.next_url == mock_get.return_value.get.call_args_list[0].args[0]

    def test_workflow_runs_envelope_is_unwrapped(self) -> None:
        manager = _make_manager(can_resume=False)
        envelope = {"total_count": 1, "workflow_runs": [{"id": 1001, "created_at": "2026-01-20T10:00:00Z"}]}

        with (
            self._patch_batcher(),
            mock.patch(
                "posthog.temporal.data_imports.sources.github.github.make_tracked_session",
            ) as mock_get,
        ):
            mock_get.return_value.get.side_effect = [_make_response(body=envelope, link="")]
            rows = list(
                get_rows(
                    personal_access_token="tok",
                    repository="owner/repo",
                    endpoint="workflow_runs",
                    logger=mock.Mock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=False,
                )
            )

        assert len(rows) == 1
        assert rows[0]["id"] == 1001

    def test_workflow_runs_empty_envelope_ends_loop(self) -> None:
        manager = _make_manager(can_resume=False)
        envelope = {"total_count": 0, "workflow_runs": []}

        with (
            self._patch_batcher(),
            mock.patch(
                "posthog.temporal.data_imports.sources.github.github.make_tracked_session",
            ) as mock_get,
        ):
            mock_get.return_value.get.side_effect = [_make_response(body=envelope, link="")]
            rows = list(
                get_rows(
                    personal_access_token="tok",
                    repository="owner/repo",
                    endpoint="workflow_runs",
                    logger=mock.Mock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=False,
                )
            )

        assert rows == []
        manager.save_state.assert_not_called()

    def test_workflow_runs_incremental_stops_at_cutoff_without_filter(self) -> None:
        """Incremental workflow_runs paginates newest-first and stops once a
        page crosses below the cursor — never sending a `created`/`since`
        filter (which would cap results at 1,000). A page past the cutoff must
        not be fetched."""
        manager = _make_manager(can_resume=False)
        cutoff = datetime(2026, 1, 20, tzinfo=UTC)
        page1 = {
            "total_count": 3,
            "workflow_runs": [
                {"id": 3, "created_at": "2026-01-25T00:00:00Z"},
                {"id": 2, "created_at": "2026-01-22T00:00:00Z"},
            ],
        }
        page2 = {"total_count": 3, "workflow_runs": [{"id": 1, "created_at": "2026-01-18T00:00:00Z"}]}
        link_page1 = '<https://api.github.com/repos/owner/repo/actions/runs?page=2>; rel="next"'
        # Only two responses are provided: a fetch of page 3 would raise
        # StopIteration, so the test fails if early-stop doesn't fire.
        responses = [
            _make_response(body=page1, link=link_page1),
            _make_response(
                body=page2, link='<https://api.github.com/repos/owner/repo/actions/runs?page=3>; rel="next"'
            ),
        ]

        with (
            self._patch_batcher(),
            mock.patch(
                "posthog.temporal.data_imports.sources.github.github.make_tracked_session",
            ) as mock_get,
        ):
            mock_get.return_value.get.side_effect = responses
            rows = list(
                get_rows(
                    personal_access_token="tok",
                    repository="owner/repo",
                    endpoint="workflow_runs",
                    logger=mock.Mock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=cutoff,
                    incremental_field="created_at",
                )
            )

        assert [row["id"] for row in rows] == [3, 2, 1]
        assert mock_get.return_value.get.call_count == 2
        first_url = mock_get.return_value.get.call_args_list[0].args[0]
        assert "created=" not in first_url
        assert "since=" not in first_url
        assert "/actions/runs" in first_url

    def test_mid_page_chunk_boundary_checkpoints_current_page(self) -> None:
        """If the chunk boundary lands mid-page, the checkpoint must point at
        the CURRENT page (not the next), so trailing unyielded items are
        re-fetched on resume instead of dropped.
        """
        manager = _make_manager(can_resume=False)
        page1 = [{"id": 1}, {"id": 2}, {"id": 3}]
        link_page1 = '<https://api.github.com/repos/owner/repo/releases?page=2>; rel="next"'
        page2: list[dict[str, Any]] = []
        responses = [
            _make_response(body=page1, link=link_page1),
            _make_response(body=page2, link=""),
        ]

        # Batcher yields after every 2 items — so page 1 (3 items) produces
        # one yield at the 2nd item, with item 3 still buffered but not yielded.
        def batcher_factory(logger: Any, chunk_size: int, chunk_size_bytes: int) -> Any:
            return _ChunkingBatcher(yield_every=2)

        with (
            mock.patch(
                "posthog.temporal.data_imports.sources.github.github.Batcher",
                autospec=False,
                side_effect=batcher_factory,
            ),
            mock.patch(
                "posthog.temporal.data_imports.sources.github.github.make_tracked_session",
            ) as mock_get,
        ):
            mock_get.return_value.get.side_effect = responses
            list(
                get_rows(
                    personal_access_token="tok",
                    repository="owner/repo",
                    endpoint="releases",
                    logger=mock.Mock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=False,
                )
            )

        # The mid-page save_state must checkpoint the CURRENT page URL, not
        # the next-page URL — otherwise item 3 (batched but not yet yielded)
        # would be skipped on resume.
        first_save = manager.save_state.call_args_list[0].args[0]
        assert first_save.next_url == mock_get.return_value.get.call_args_list[0].args[0]
        assert first_save.next_url != "https://api.github.com/repos/owner/repo/releases?page=2"


class _ChunkingBatcher:
    """Test double for Batcher that yields after every `yield_every` batched items."""

    def __init__(self, yield_every: int) -> None:
        self._yield_every = yield_every
        self._buffer: list[Any] = []
        self._ready: list[Any] | None = None

    def batch(self, item: Any) -> None:
        self._buffer.append(item)
        if len(self._buffer) >= self._yield_every:
            self._ready = self._buffer
            self._buffer = []

    def should_yield(self, include_incomplete_chunk: bool = False) -> bool:
        if include_incomplete_chunk:
            return self._ready is not None or bool(self._buffer)
        return self._ready is not None

    def get_table(self) -> Any:
        if self._ready is not None:
            table = self._ready
            self._ready = None
            return table
        if self._buffer:
            table = self._buffer
            self._buffer = []
            return table
        raise Exception("No chunks available to yield")


class _RoutingSession:
    """Routes GitHub GET calls by URL so two-level runs->jobs fan-out can be mocked
    without depending on request order. Records every requested URL."""

    def __init__(
        self,
        runs_pages: list[tuple[Any, str]],
        jobs_by_run: dict[int, tuple[Any, str]],
    ) -> None:
        self._runs_pages = list(runs_pages)
        self._jobs_by_run = jobs_by_run
        self.calls: list[str] = []

    def get(self, url: str, headers: Any = None, timeout: Any = None) -> Any:
        self.calls.append(url)
        if "/jobs" in url:
            run_id = int(urlparse(url).path.split("/")[-2])
            body, link = self._jobs_by_run.get(run_id, ({"total_count": 0, "jobs": []}, ""))
            return _make_response(body=body, link=link)
        body, link = self._runs_pages.pop(0)
        return _make_response(body=body, link=link)


def _run(created_at: str, run_id: int) -> dict[str, Any]:
    return {"id": run_id, "created_at": created_at}


def _runs_envelope(*runs: dict[str, Any]) -> dict[str, Any]:
    return {"total_count": len(runs), "workflow_runs": list(runs)}


def _jobs_envelope(*jobs: dict[str, Any]) -> dict[str, Any]:
    return {"total_count": len(jobs), "jobs": list(jobs)}


class TestFanOutJobs:
    """workflow_jobs fans out over workflow_runs and emits each run's jobs."""

    def _patch_batcher(self) -> Any:
        return mock.patch(
            "posthog.temporal.data_imports.sources.github.github.Batcher",
            autospec=False,
            side_effect=lambda logger, chunk_size, chunk_size_bytes: _ImmediateBatcher(),
        )

    def _fan_out(self, session: _RoutingSession, **kwargs: Any) -> list[Any]:
        with (
            self._patch_batcher(),
            mock.patch(
                "posthog.temporal.data_imports.sources.github.github.make_tracked_session",
                return_value=session,
            ),
        ):
            return list(
                get_rows(
                    personal_access_token="tok",
                    repository="owner/repo",
                    endpoint="workflow_jobs",
                    logger=mock.Mock(),
                    resumable_source_manager=_make_manager(),
                    **kwargs,
                )
            )

    def test_each_job_carries_run_id_and_nested_steps(self) -> None:
        session = _RoutingSession(
            runs_pages=[(_runs_envelope(_run("2026-01-22T00:00:00Z", 1002), _run("2026-01-20T00:00:00Z", 1001)), "")],
            jobs_by_run={
                1002: (_jobs_envelope({"id": 3, "run_id": 1002, "steps": [{"name": "test", "number": 1}]}), ""),
                1001: (
                    _jobs_envelope(
                        {"id": 1, "run_id": 1001, "steps": [{"name": "build", "number": 1}]},
                        {"id": 2, "run_id": 1001, "steps": []},
                    ),
                    "",
                ),
            },
        )

        rows = self._fan_out(session, should_use_incremental_field=False)

        assert [row["id"] for row in rows] == [3, 1, 2]
        assert all("run_id" in row for row in rows)
        # steps[] is yielded nested (a list), not pre-flattened or stringified —
        # the pipeline JSON-serializes it on write.
        assert rows[0]["steps"] == [{"name": "test", "number": 1}]
        assert isinstance(rows[1]["steps"], list)

    def test_child_request_uses_filter_all_and_per_page_only(self) -> None:
        session = _RoutingSession(
            runs_pages=[(_runs_envelope(_run("2026-01-20T00:00:00Z", 1001)), "")],
            jobs_by_run={1001: (_jobs_envelope({"id": 1, "run_id": 1001}), "")},
        )

        self._fan_out(session, should_use_incremental_field=False)

        jobs_calls = [c for c in session.calls if "/jobs" in c]
        assert len(jobs_calls) == 1
        assert "/repos/owner/repo/actions/runs/1001/jobs" in jobs_calls[0]
        params = parse_qs(urlparse(jobs_calls[0]).query)
        assert params["filter"] == ["all"]
        assert params["per_page"] == ["100"]
        # No params that would trip the parent's 1,000-result search cap or are
        # unsupported on the jobs endpoint.
        assert "since" not in params
        assert "created" not in params
        assert "sort" not in params
        assert "state" not in params

    def test_null_jobs_envelope_does_not_crash_or_truncate(self) -> None:
        session = _RoutingSession(
            runs_pages=[(_runs_envelope(_run("2026-01-22T00:00:00Z", 1002), _run("2026-01-20T00:00:00Z", 1001)), "")],
            jobs_by_run={
                1002: ({"total_count": 0, "jobs": None}, ""),  # run with no jobs yet
                1001: (_jobs_envelope({"id": 1, "run_id": 1001}), ""),
            },
        )

        rows = self._fan_out(session, should_use_incremental_field=False)

        # Empty/null envelope for one run contributes nothing; the other run's
        # jobs still land.
        assert [row["id"] for row in rows] == [1]

    def test_incremental_fans_out_only_runs_at_or_above_cutoff(self) -> None:
        cutoff = datetime(2026, 1, 22, tzinfo=UTC)
        # Runs are newest-first. 1003 is above the cutoff; 1001 is below it.
        session = _RoutingSession(
            runs_pages=[(_runs_envelope(_run("2026-01-25T00:00:00Z", 1003), _run("2026-01-20T00:00:00Z", 1001)), "")],
            jobs_by_run={
                1003: (_jobs_envelope({"id": 9, "run_id": 1003}), ""),
                1001: (_jobs_envelope({"id": 1, "run_id": 1001}), ""),
            },
        )

        rows = self._fan_out(
            session,
            should_use_incremental_field=True,
            db_incremental_field_last_value=cutoff,
            incremental_field="created_at",
        )

        # Only the run above the cutoff is fanned out; the older run is skipped
        # entirely — no jobs request is made for it.
        assert [row["id"] for row in rows] == [9]
        jobs_calls = [c for c in session.calls if "/jobs" in c]
        assert any("/runs/1003/jobs" in c for c in jobs_calls)
        assert not any("/runs/1001/jobs" in c for c in jobs_calls)

    def test_resume_starts_from_saved_parent_page_url(self) -> None:
        saved_url = "https://api.github.com/repos/owner/repo/actions/runs?per_page=100&page=3"
        manager = _make_manager(can_resume=True, resume_state=GithubResumeConfig(next_url=saved_url))
        session = _RoutingSession(
            runs_pages=[(_runs_envelope(_run("2026-01-20T00:00:00Z", 1001)), "")],
            jobs_by_run={1001: (_jobs_envelope({"id": 1, "run_id": 1001}), "")},
        )

        with (
            self._patch_batcher(),
            mock.patch(
                "posthog.temporal.data_imports.sources.github.github.make_tracked_session",
                return_value=session,
            ),
        ):
            list(
                get_rows(
                    personal_access_token="tok",
                    repository="owner/repo",
                    endpoint="workflow_jobs",
                    logger=mock.Mock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=False,
                )
            )

        assert session.calls[0] == saved_url
        manager.load_state.assert_called_once()


class TestIterPages:
    """Generic paginator shared by the fan-out: envelope unwrap, Link following,
    and the per-parent page cap."""

    def test_unwraps_envelope_and_follows_link(self) -> None:
        responses = [
            _make_response(
                body={"total_count": 3, "jobs": [{"id": 1}]},
                link='<https://api.github.com/x?page=2>; rel="next"',
            ),
            _make_response(body={"total_count": 3, "jobs": [{"id": 2}]}, link=""),
        ]
        with mock.patch(
            "posthog.temporal.data_imports.sources.github.github.make_tracked_session",
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            pages = list(_iter_pages("https://api.github.com/x", {}, "jobs", mock.Mock()))

        assert [items for items, _url, _next in pages] == [[{"id": 1}], [{"id": 2}]]

    @parameterized.expand(
        [
            ("null_body", {"total_count": 0, "jobs": None}),
            ("empty_dict", {}),
            ("empty_list", {"total_count": 0, "jobs": []}),
        ]
    )
    def test_empty_or_null_envelope_yields_no_pages(self, _name: str, body: Any) -> None:
        with mock.patch(
            "posthog.temporal.data_imports.sources.github.github.make_tracked_session",
        ) as mock_get:
            mock_get.return_value.get.side_effect = [_make_response(body=body, link="")]
            pages = list(_iter_pages("https://api.github.com/x", {}, "jobs", mock.Mock()))

        assert pages == []

    def test_page_cap_stops_and_logs(self) -> None:
        # Every page links to a next page; the cap must halt pagination.
        responses = [
            _make_response(body={"jobs": [{"id": i}]}, link='<https://api.github.com/x?page=n>; rel="next"')
            for i in range(5)
        ]
        logger = mock.Mock()
        with mock.patch(
            "posthog.temporal.data_imports.sources.github.github.make_tracked_session",
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            pages = list(
                _iter_pages(
                    "https://api.github.com/x",
                    {},
                    "jobs",
                    logger,
                    max_pages=2,
                    page_cap_context={"repository": "owner/repo", "run_id": 1001},
                )
            )

        assert len(pages) == 2
        logger.warning.assert_called_once()
        assert logger.warning.call_args.kwargs["max_pages"] == 2
        assert logger.warning.call_args.kwargs["run_id"] == 1001

    def test_iter_jobs_for_run_builds_path_and_passes_cap(self) -> None:
        config = dataclasses.replace(GITHUB_ENDPOINTS["workflow_jobs"], max_pages_per_parent=1)
        responses = [
            _make_response(
                body=_jobs_envelope({"id": 1, "run_id": 1001}),
                link='<https://api.github.com/x?page=2>; rel="next"',
            ),
        ]
        logger = mock.Mock()
        with mock.patch(
            "posthog.temporal.data_imports.sources.github.github.make_tracked_session",
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            jobs = list(_iter_jobs_for_run("owner/repo", 1001, {}, logger, config))

        assert [job["id"] for job in jobs] == [1]
        url = mock_get.return_value.get.call_args_list[0].args[0]
        assert "/repos/owner/repo/actions/runs/1001/jobs" in url
        assert "filter=all" in url
        # Cap of 1 page reached (a next link exists) → warning emitted.
        logger.warning.assert_called_once()
