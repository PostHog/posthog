import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from tenacity import Future, RetryCallState

from posthog.egress.github.transport import GitHubRateLimitError

from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    GithubAuthMethodConfig,
    GithubSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.github.github import (
    GITHUB_MAX_RETRY_AFTER_SECONDS,
    GithubResumeConfig,
    GithubRetryableError,
    _build_initial_params,
    _build_initial_url,
    _fetch_page,
    _flatten_commit,
    _flatten_stargazer,
    _format_incremental_value,
    _github_retry_wait,
    _is_empty_repository_response,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.github.settings import GITHUB_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.github.source import GithubSource


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


class TestIsEmptyRepositoryResponse:
    @parameterized.expand(
        [
            ("conflict_empty_repo", 409, {"message": "Git Repository is empty."}, True),
            ("conflict_empty_repo_lowercase", 409, {"message": "git repository is empty"}, True),
            ("conflict_other_message", 409, {"message": "Merge conflict"}, False),
            ("conflict_no_body", 409, [], False),
            ("not_conflict_status", 404, {"message": "Git Repository is empty."}, False),
            ("ok_status", 200, [{"sha": "abc"}], False),
        ]
    )
    def test_detects_empty_repository(self, _name: str, status: int, body: Any, expected: bool) -> None:
        assert _is_empty_repository_response(_make_response(status=status, body=body)) is expected


class TestValidateCredentials:
    def test_valid_credentials(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session"
        ) as mock_get:
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
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.return_value = mock.MagicMock(status_code=status_code)
            valid, error = validate_credentials("token", "owner/repo")

        assert valid is False
        assert error == expected_message

    def test_json_error_response(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session"
        ) as mock_get:
            mock_response = mock.MagicMock(status_code=403)
            mock_response.json.return_value = {"message": "API rate limit exceeded"}
            mock_get.return_value.get.return_value = mock_response
            valid, error = validate_credentials("token", "owner/repo")

        assert valid is False
        assert error == "API rate limit exceeded"

    def test_request_exception(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = requests.exceptions.ConnectionError("Connection refused")
            valid, error = validate_credentials("token", "owner/repo")

        assert valid is False
        assert error is not None
        assert "Connection refused" in error

    def test_sends_correct_headers(self) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session"
        ) as mock_get:
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


# A fresh webhook schema must not deadlock: workflow_jobs does no poll backfill
# (initial_lookback_days == 0), so webhook mode has to activate before the zero-row
# poll could mark initial_sync_complete — otherwise the gate never opens and queued
# webhook files never drain. workflow_runs (and the non-webhook endpoints) keep their
# historical poll backfill, so they must NOT skip that gate.
class TestGithubWebhookActivationGate:
    def _make_webhook_manager(self, enabled: bool) -> mock.Mock:
        manager = mock.Mock()
        manager.webhook_enabled = mock.AsyncMock(return_value=enabled)
        manager.get_items = mock.Mock(return_value=iter([{"id": 1}]))
        return manager

    @parameterized.expand(
        [
            ("workflow_jobs_skips_gate", "workflow_jobs", True),
            ("workflow_runs_keeps_gate", "workflow_runs", False),
            ("issues_keeps_gate", "issues", False),
        ]
    )
    def test_skip_check_scoped_to_zero_backfill_endpoint(self, _name: str, endpoint: str, expected_skip: bool) -> None:
        manager = self._make_webhook_manager(enabled=False)
        github_source(
            personal_access_token="token",
            repository="owner/repo",
            endpoint=endpoint,
            logger=mock.Mock(),
            resumable_source_manager=_make_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            webhook_source_manager=manager,
        )
        manager.webhook_enabled.assert_called_once_with(expected_skip)

    def test_webhook_path_drains_manager_when_enabled(self) -> None:
        # Gate skipped + webhook_enabled True: items() reads the webhook manager (S3
        # parquet) instead of running the zero-row workflow_jobs poll.
        manager = self._make_webhook_manager(enabled=True)
        response = github_source(
            personal_access_token="token",
            repository="owner/repo",
            endpoint="workflow_jobs",
            logger=mock.Mock(),
            resumable_source_manager=_make_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            webhook_source_manager=manager,
        )
        # items() is typed Iterator | AsyncIterator; the webhook path returns the sync one.
        assert list(cast(Iterator[Any], response.items())) == [{"id": 1}]
        manager.get_items.assert_called_once()


class TestGetRowsResume:
    """Integration tests for the fresh-run and resume flows in get_rows."""

    def _patch_batcher(self) -> Any:
        return mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.Batcher",
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
                "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
            ) as mock_get,
        ):
            mock_get.return_value.request.side_effect = responses
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

        first_url = mock_get.return_value.request.call_args_list[0].args[1]
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
                "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
            ) as mock_get,
        ):
            mock_get.return_value.request.side_effect = responses
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

        assert mock_get.return_value.request.call_args_list[0].args[1] == saved_url
        manager.load_state.assert_called_once()

    def test_empty_first_page_ends_loop(self) -> None:
        manager = _make_manager(can_resume=False)
        with (
            self._patch_batcher(),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
            ) as mock_get,
        ):
            mock_get.return_value.request.side_effect = [_make_response(body=[], link="")]
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
                "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
            ) as mock_get,
        ):
            mock_get.return_value.request.side_effect = [_make_response(body=[{"id": 1}], link="")]
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
        assert saved.next_url == mock_get.return_value.request.call_args_list[0].args[1]

    def test_empty_repository_409_syncs_zero_rows(self) -> None:
        """An empty repo returns 409 "Git Repository is empty." on the commits
        endpoint. That's a benign state, not an error — get_rows must yield zero
        rows and not raise (otherwise the activity retries indefinitely)."""
        manager = _make_manager(can_resume=False)
        empty_repo_409 = _make_response(status=409, body={"message": "Git Repository is empty."})

        with (
            self._patch_batcher(),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
            ) as mock_get,
        ):
            mock_get.return_value.request.side_effect = [empty_repo_409]
            rows = list(
                get_rows(
                    personal_access_token="tok",
                    repository="owner/repo",
                    endpoint="commits",
                    logger=mock.Mock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=False,
                )
            )

        assert rows == []
        manager.save_state.assert_not_called()

    def test_non_empty_repo_409_still_raises(self) -> None:
        """A 409 that is NOT the empty-repository case must still surface as an
        error rather than being silently swallowed as zero rows."""
        manager = _make_manager(can_resume=False)
        other_409 = _make_response(status=409, body={"message": "Merge conflict"})
        other_409.text = '{"message": "Merge conflict"}'
        other_409.raise_for_status.side_effect = requests.HTTPError(
            "409 Client Error: Conflict for url: ...", response=other_409
        )

        with (
            self._patch_batcher(),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
            ) as mock_get,
        ):
            mock_get.return_value.request.side_effect = [other_409]
            with pytest.raises(requests.HTTPError):
                list(
                    get_rows(
                        personal_access_token="tok",
                        repository="owner/repo",
                        endpoint="commits",
                        logger=mock.Mock(),
                        resumable_source_manager=manager,
                        should_use_incremental_field=False,
                    )
                )

    def test_workflow_runs_envelope_is_unwrapped(self) -> None:
        manager = _make_manager(can_resume=False)
        envelope = {"total_count": 1, "workflow_runs": [{"id": 1001, "created_at": "2026-01-20T10:00:00Z"}]}

        with (
            self._patch_batcher(),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
            ) as mock_get,
        ):
            mock_get.return_value.request.side_effect = [_make_response(body=envelope, link="")]
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
                "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
            ) as mock_get,
        ):
            mock_get.return_value.request.side_effect = [_make_response(body=envelope, link="")]
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
                "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
            ) as mock_get,
        ):
            mock_get.return_value.request.side_effect = responses
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
        assert mock_get.return_value.request.call_count == 2
        first_url = mock_get.return_value.request.call_args_list[0].args[1]
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
                "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.Batcher",
                autospec=False,
                side_effect=batcher_factory,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
            ) as mock_get,
        ):
            mock_get.return_value.request.side_effect = responses
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
        assert first_save.next_url == mock_get.return_value.request.call_args_list[0].args[1]
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


class TestGithubSourceNonRetryableErrors:
    def setup_method(self) -> None:
        self.source = GithubSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.GITHUB

    @parameterized.expand(
        [
            ("401",),
            ("403",),
            ("404",),
            ("bad_credentials",),
            ("missing_integration_id",),
            ("client_id_not_configured",),
            ("private_key_not_configured",),
        ]
    )
    def test_non_retryable_errors_contains_key(self, _name: str) -> None:
        expected_keys = {
            "401": "401 Client Error",
            "403": "403 Client Error",
            "404": "404 Client Error",
            "bad_credentials": "Bad credentials",
            "missing_integration_id": "Missing GitHub integration ID",
            "client_id_not_configured": "GITHUB_APP_CLIENT_ID is not configured",
            "private_key_not_configured": "GITHUB_APP_PRIVATE_KEY is not configured",
        }
        assert expected_keys[_name] in self.source.get_non_retryable_errors()

    def test_oauth_without_integration_id_raises_non_retryable_error(self) -> None:
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(selection="oauth", github_integration_id=None),
            repository="owner/repo",
        )

        with pytest.raises(ValueError) as exc_info:
            self.source._get_access_token(config, team_id=123)

        # The raised message must stay a recognised non-retryable substring so a misconfigured
        # OAuth source stops retrying instead of failing forever.
        assert any(key in str(exc_info.value) for key in self.source.get_non_retryable_errors())

    @parameterized.expand(
        [
            ("[ErrorDetail(string='GITHUB_APP_CLIENT_ID is not configured', code='invalid')]",),
            ("[ErrorDetail(string='GITHUB_APP_PRIVATE_KEY is not configured', code='invalid')]",),
        ]
    )
    def test_app_not_configured_is_recognised_as_non_retryable(self, internal_error: str) -> None:
        # Mirrors the substring match done in external_data_job.update_external_data_job_model.
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(pattern in internal_error for pattern in non_retryable_errors)

    @parameterized.expand(
        [
            # GitHub returns this body verbatim when the App installation no longer exists; matching it
            # stops the pipeline from retrying a token refresh that can never succeed.
            (
                "not_found",
                'Failed to refresh installation token: {"message":"Not Found",'
                '"documentation_url":"https://docs.github.com/rest/reference/apps'
                '#create-an-installation-access-token-for-an-app","status":"404"}',
                True,
            ),
            # A 5xx during token refresh is transient and must stay retryable, so the generic
            # "Failed to refresh installation token" prefix must not match on its own.
            (
                "server_error",
                'Failed to refresh installation token: {"message":"Server Error","status":"500"}',
                False,
            ),
        ]
    )
    def test_installation_token_refresh_non_retryable_matching(
        self, _name: str, error_message: str, expected_match: bool
    ) -> None:
        # Mirrors the substring match done in external_data_job.update_external_data_job_model.
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(pattern in error_message for pattern in non_retryable_errors) == expected_match


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

    def request(self, method: str, url: str, headers: Any = None, timeout: Any = None, **kwargs: Any) -> Any:
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
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.Batcher",
            autospec=False,
            side_effect=lambda logger, chunk_size, chunk_size_bytes: _ImmediateBatcher(),
        )

    def _fan_out(self, session: _RoutingSession, **kwargs: Any) -> list[Any]:
        with (
            self._patch_batcher(),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
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
                1002: (
                    _jobs_envelope(
                        {
                            "id": 3,
                            "run_id": 1002,
                            "steps": [{"name": "test", "number": 1}],
                            "labels": ["depot-ubuntu-latest-4"],
                        }
                    ),
                    "",
                ),
                1001: (
                    _jobs_envelope(
                        {"id": 1, "run_id": 1001, "steps": [{"name": "build", "number": 1}], "labels": []},
                        {"id": 2, "run_id": 1001, "steps": []},
                    ),
                    "",
                ),
            },
        )

        rows = self._fan_out(session, should_use_incremental_field=False)

        assert [row["id"] for row in rows] == [3, 1, 2]
        assert all("run_id" in row for row in rows)
        # steps[] and labels[] are yielded nested (lists), not pre-flattened or
        # stringified — the pipeline JSON-serializes them on write.
        assert rows[0]["steps"] == [{"name": "test", "number": 1}]
        assert rows[0]["labels"] == ["depot-ubuntu-latest-4"]
        assert isinstance(rows[1]["steps"], list)
        assert isinstance(rows[1]["labels"], list)

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

    def _make_first_sync_session(self) -> tuple[datetime, _RoutingSession]:
        # Two runs newest-first: 1003 a day before the frozen now, 1001 over a month back.
        frozen_now = datetime(2026, 2, 20, tzinfo=UTC)
        session = _RoutingSession(
            runs_pages=[(_runs_envelope(_run("2026-02-19T00:00:00Z", 1003), _run("2026-01-10T00:00:00Z", 1001)), "")],
            jobs_by_run={
                1003: (_jobs_envelope({"id": 9, "run_id": 1003}), ""),
                1001: (_jobs_envelope({"id": 1, "run_id": 1001}), ""),
            },
        )
        return frozen_now, session

    def _fan_out_with_lookback(self, session: _RoutingSession, lookback_days: int | None, **kwargs: Any) -> list[Any]:
        # Override the production initial_lookback_days so the floor mechanism can be
        # tested independently of whatever default the workflow_jobs endpoint ships.
        patched = dict(GITHUB_ENDPOINTS)
        patched["workflow_jobs"] = dataclasses.replace(
            GITHUB_ENDPOINTS["workflow_jobs"], initial_lookback_days=lookback_days
        )
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.GITHUB_ENDPOINTS", patched
        ):
            return self._fan_out(session, **kwargs)

    def test_first_incremental_sync_floors_fan_out_to_lookback_window(self) -> None:
        # First incremental sync (watermark configured, nothing synced yet) with a
        # non-zero floor: the backfill is bounded at initial_lookback_days instead of
        # crawling all history. 1003 is inside a 30-day window, 1001 is outside.
        frozen_now, session = self._make_first_sync_session()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github._now_utc",
            return_value=frozen_now,
        ):
            rows = self._fan_out_with_lookback(
                session,
                lookback_days=30,
                should_use_incremental_field=True,
                db_incremental_field_last_value=None,
            )

        # Only the run inside the lookback window is fanned out; the older one is
        # skipped without a jobs request.
        assert [row["id"] for row in rows] == [9]
        jobs_calls = [c for c in session.calls if "/jobs" in c]
        assert any("/runs/1003/jobs" in c for c in jobs_calls)
        assert not any("/runs/1001/jobs" in c for c in jobs_calls)

    def test_first_incremental_sync_does_no_backfill_by_default(self) -> None:
        # The shipped default is initial_lookback_days=0: the per-run fan-out is too
        # expensive to backfill at high run volume, so the first sync fans out over
        # nothing and the webhook becomes the source of truth. Both historical runs
        # are skipped — no jobs request is made for either.
        frozen_now, session = self._make_first_sync_session()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github._now_utc",
            return_value=frozen_now,
        ):
            rows = self._fan_out(
                session,
                should_use_incremental_field=True,
                db_incremental_field_last_value=None,
            )

        assert rows == []
        assert not any("/jobs" in c for c in session.calls)

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
                "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
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
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
        ) as mock_get:
            mock_get.return_value.request.side_effect = responses
            pages = list(_iter_pages("https://api.github.com/x", {}, "jobs", mock.Mock()))

        assert [items for items, _url in pages] == [[{"id": 1}], [{"id": 2}]]

    @parameterized.expand(
        [
            ("null_body", {"total_count": 0, "jobs": None}),
            ("empty_dict", {}),
            ("empty_list", {"total_count": 0, "jobs": []}),
        ]
    )
    def test_empty_or_null_envelope_yields_no_pages(self, _name: str, body: Any) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
        ) as mock_get:
            mock_get.return_value.request.side_effect = [_make_response(body=body, link="")]
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
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
        ) as mock_get:
            mock_get.return_value.request.side_effect = responses
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
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
        ) as mock_get:
            mock_get.return_value.request.side_effect = responses
            jobs = list(_iter_jobs_for_run("owner/repo", 1001, {}, logger, config))

        assert [job["id"] for job in jobs] == [1]
        url = mock_get.return_value.request.call_args_list[0].args[1]
        assert "/repos/owner/repo/actions/runs/1001/jobs" in url
        assert "filter=all" in url
        # Cap of 1 page reached (a next link exists) → warning emitted.
        logger.warning.assert_called_once()


def _pat_config() -> GithubSourceConfig:
    return GithubSourceConfig(
        auth_method=GithubAuthMethodConfig(selection="pat", personal_access_token="test-token"),
        repository="owner/repo",
    )


class TestGithubWebhookSource:
    """The WebhookSource surface: event mapping, schema flags, and the create/
    delete/info round-trips that mint and reconcile the repo webhook."""

    def setup_method(self) -> None:
        self.source = GithubSource()

    def test_webhook_resource_map(self) -> None:
        assert self.source.webhook_resource_map == {
            "workflow_jobs": "workflow_job",
            "workflow_runs": "workflow_run",
        }

    def test_webhook_template_identity(self) -> None:
        template = self.source.webhook_template
        assert template is not None
        assert template.id == "template-warehouse-source-github"
        assert template.type == "warehouse_source_webhook"

    def test_get_schemas_marks_only_workflow_schemas_webhook_capable(self) -> None:
        schemas = self.source.get_schemas(_pat_config(), team_id=1)
        webhook_capable = {s.name for s in schemas if s.supports_webhooks}
        assert webhook_capable == {"workflow_jobs", "workflow_runs"}

    def test_workflow_jobs_is_webhook_only_but_workflow_runs_keeps_poll(self) -> None:
        # workflow_jobs does no poll backfill (zero floor), so it must not be offered as a
        # poll mode that would sync an empty table forever — it's webhook-only. workflow_runs
        # still has a real poll backfill and stays incremental/append-capable.
        by_name = {s.name: s for s in self.source.get_schemas(_pat_config(), team_id=1)}

        jobs = by_name["workflow_jobs"]
        assert jobs.webhook_only is True
        assert jobs.supports_incremental is False
        assert jobs.supports_append is False
        assert jobs.supports_webhooks is True

        runs = by_name["workflow_runs"]
        assert runs.webhook_only is False
        assert runs.supports_incremental is True
        assert runs.supports_webhooks is True

    @parameterized.expand(
        [
            ("both", ["workflow_jobs", "workflow_runs"], ["workflow_job", "workflow_run"]),
            ("jobs_only", ["workflow_jobs"], ["workflow_job"]),
            ("drops_non_webhook_schemas", ["workflow_jobs", "issues", "commits"], ["workflow_job"]),
        ]
    )
    def test_get_desired_webhook_events(self, _name: str, eligible: list[str], expected_events: list[str]) -> None:
        assert self.source.get_desired_webhook_events(_pat_config(), eligible) == expected_events

    def test_create_webhook_sends_secret_and_returns_it_as_extra_input(self) -> None:
        captured: dict[str, Any] = {}

        def post(url: str, headers: Any = None, json: Any = None, timeout: Any = None) -> Any:
            captured["url"] = url
            captured["json"] = json
            return _make_response(status=201, body={"id": 99})

        session = mock.Mock()
        session.post.side_effect = post

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
            return_value=session,
        ):
            result = self.source.create_webhook(_pat_config(), "https://app.posthog.com/webhook", team_id=1)

        assert "/repos/owner/repo/hooks" in captured["url"]
        sent_secret = captured["json"]["config"]["secret"]
        assert sent_secret  # a non-empty secret is minted and handed to GitHub
        assert result.success is True
        # GitHub never echoes the secret, so create_webhook returns the minted one
        # for the framework to persist as the hog function's signing_secret.
        assert result.extra_inputs["signing_secret"] == sent_secret

    def test_create_webhook_permission_error_falls_back_to_manual(self) -> None:
        session = mock.Mock()
        session.post.return_value = _make_response(status=403, body={"message": "Forbidden"})

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
            return_value=session,
        ):
            result = self.source.create_webhook(_pat_config(), "https://app.posthog.com/webhook", team_id=1)

        assert result.success is False
        assert result.error is not None
        assert "admin:repo_hook" in result.error

    def test_delete_webhook_lists_then_deletes_matching_hook(self) -> None:
        webhook_url = "https://app.posthog.com/webhook"
        session = mock.Mock()
        session.get.return_value = _make_response(status=200, body=[{"id": 42, "config": {"url": webhook_url}}])
        session.delete.return_value = _make_response(status=204)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
            return_value=session,
        ):
            result = self.source.delete_webhook(_pat_config(), webhook_url, team_id=1)

        assert result.success is True
        delete_url = session.delete.call_args.args[0]
        assert "/repos/owner/repo/hooks/42" in delete_url

    def test_get_external_webhook_info_reports_existing_hook(self) -> None:
        webhook_url = "https://app.posthog.com/webhook"
        session = mock.Mock()
        session.get.return_value = _make_response(
            status=200,
            body=[
                {
                    "id": 42,
                    "active": True,
                    "events": ["workflow_job", "workflow_run"],
                    "config": {"url": webhook_url},
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
        )

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
            return_value=session,
        ):
            info = self.source.get_external_webhook_info(_pat_config(), webhook_url, team_id=1)

        assert info.exists is True
        assert info.url == webhook_url
        assert info.status == "active"
        assert info.enabled_events == ["workflow_job", "workflow_run"]

    def test_delete_webhook_treats_404_as_success(self) -> None:
        # The hook is found in the list but DELETE races a concurrent removal and
        # 404s — the desired end state, so it must not surface as a permission error.
        webhook_url = "https://app.posthog.com/webhook"
        session = mock.Mock()
        session.get.return_value = _make_response(status=200, body=[{"id": 42, "config": {"url": webhook_url}}])
        session.delete.return_value = _make_response(status=404, body={"message": "Not Found"})

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
            return_value=session,
        ):
            result = self.source.delete_webhook(_pat_config(), webhook_url, team_id=1)

        assert result.success is True
        assert result.error is None

    def test_get_external_webhook_info_skips_hook_with_null_config(self) -> None:
        # A hook whose `config` is present-but-null must be skipped, not crash the
        # match loop — the real hook still resolves.
        webhook_url = "https://app.posthog.com/webhook"
        session = mock.Mock()
        session.get.return_value = _make_response(
            status=200,
            body=[
                {"id": 7, "config": None},
                {"id": 42, "active": True, "events": ["workflow_job"], "config": {"url": webhook_url}},
            ],
        )

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session",
            return_value=session,
        ):
            info = self.source.get_external_webhook_info(_pat_config(), webhook_url, team_id=1)

        assert info.exists is True
        assert info.url == webhook_url


# A response that raise_if_github_rate_limited classifies as rate limited: 429 is
# rate limited regardless of body, 403 only when the body mentions a rate limit.
# headers carry x-ratelimit-reset / retry-after for the wait.
def _rate_limited_response(status: int, body_text: str, headers: dict[str, str]) -> mock.Mock:
    resp = mock.Mock()
    resp.status_code = status
    resp.text = body_text
    resp.headers = headers
    return resp


def _retry_state_with_exception(exc: BaseException) -> RetryCallState:
    state = RetryCallState(retry_object=mock.Mock(), fn=None, args=(), kwargs={})
    state.attempt_number = 1
    state.outcome = Future.construct(1, exc, has_exception=True)
    return state


# _github_retry_wait must honor GitHub's advertised rate-limit reset (capped) and
# fall back to plain backoff for transient errors that carry no reset.
class TestGithubRetryWait:
    def test_honors_retry_after_with_jitter(self) -> None:
        wait = _github_retry_wait(_retry_state_with_exception(GitHubRateLimitError("rl", retry_after=60)))
        # The honored reset plus up to a second of jitter — not the short backoff.
        assert 60.0 <= wait <= 61.0

    def test_caps_oversized_retry_after(self) -> None:
        # A misreported reset header must not stall a worker past the cap.
        wait = _github_retry_wait(_retry_state_with_exception(GitHubRateLimitError("rl", retry_after=99999)))
        assert GITHUB_MAX_RETRY_AFTER_SECONDS <= wait <= GITHUB_MAX_RETRY_AFTER_SECONDS + 1.0

    @parameterized.expand(
        [
            # Rate limit with no parseable reset -> falls back to backoff, not a 0s spin.
            ("rate_limit_without_reset", GitHubRateLimitError("rl", retry_after=None)),
            # Transient server / connection blips never carry a reset.
            ("retryable_error", GithubRetryableError("boom")),
            ("connection_error", requests.ConnectionError("boom")),
        ]
    )
    def test_falls_back_to_backoff(self, _name: str, exc: BaseException) -> None:
        wait = _github_retry_wait(_retry_state_with_exception(exc))
        # wait_exponential_jitter(initial=1, max=30) stays well under the rate-limit cap.
        assert 0.0 <= wait <= 31.0


# _fetch_page must retry GitHub rate limits (honoring the reset) instead of treating
# the 403 as fatal, while a genuine permission 403 stays fatal.
class TestFetchPageRateLimit:
    @parameterized.expand(
        [
            # Secondary limit: 429 regardless of body.
            ("secondary_429", 429, "Too Many Requests"),
            # Primary limit: 403 whose body names a rate limit.
            ("primary_403", 403, "API rate limit exceeded for installation"),
        ]
    )
    def test_rate_limited_response_is_retried_then_reraised(self, _name: str, status: int, body_text: str) -> None:
        resp = _rate_limited_response(status, body_text, {"retry-after": "1"})

        with (
            mock.patch("time.sleep"),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session"
            ) as mock_get,
        ):
            mock_get.return_value.request.return_value = resp
            with pytest.raises(GitHubRateLimitError):
                _fetch_page("https://api.github.com/x", {}, mock.Mock())

        # stop_after_attempt(5): the rate limit is retried, not treated as fatal on first hit.
        assert mock_get.return_value.request.call_count == 5

    def test_recovers_when_rate_limit_clears(self) -> None:
        rate_limited = _rate_limited_response(429, "Too Many Requests", {"retry-after": "1"})
        ok = _make_response(status=200, body=[{"id": 1}])

        with (
            mock.patch("time.sleep"),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session"
            ) as mock_get,
        ):
            mock_get.return_value.request.side_effect = [rate_limited, ok]
            response = _fetch_page("https://api.github.com/x", {}, mock.Mock())

        assert response is ok
        assert mock_get.return_value.request.call_count == 2

    def test_permission_403_is_fatal_not_retried(self) -> None:
        # A 403 with no rate-limit body is a real permission error: surface it
        # immediately rather than burning retries on something that won't clear.
        resp = _make_response(status=403, body={"message": "Resource not accessible by integration"})
        resp.text = '{"message": "Resource not accessible by integration"}'
        resp.raise_for_status.side_effect = requests.HTTPError("403 Client Error", response=resp)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.request.return_value = resp
            with pytest.raises(requests.HTTPError):
                _fetch_page("https://api.github.com/x", {}, mock.Mock())

        assert mock_get.return_value.request.call_count == 1

    def test_disables_adapter_retries_so_cap_is_authoritative(self) -> None:
        # The tracked session's default adapter retries 429/5xx and honors Retry-After
        # uncapped, underneath us — which would defeat the 300s cap. _fetch_page must
        # request a no-retry adapter so our tenacity layer owns the backoff.
        ok = _make_response(status=200, body=[{"id": 1}])

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.github.github.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.request.return_value = ok
            _fetch_page("https://api.github.com/x", {}, mock.Mock())

        retry = mock_get.call_args.kwargs["retry"]
        assert retry.total == 0
