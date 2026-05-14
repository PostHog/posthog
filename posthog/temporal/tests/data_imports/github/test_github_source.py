from datetime import UTC, date, datetime
from typing import Any

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
