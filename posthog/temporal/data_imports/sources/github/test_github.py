from datetime import date, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized

from posthog.temporal.data_imports.sources.github.github import (
    GithubResumeConfig,
    _build_initial_params,
    _build_initial_url,
    _format_incremental_value,
    _is_older_than_cutoff,
    _parse_next_url,
    _should_stop_desc,
    get_rows,
)
from posthog.temporal.data_imports.sources.github.settings import GITHUB_ENDPOINTS


def _make_response(status: int = 200, body: Any = None, link: str = "") -> mock.Mock:
    resp = mock.Mock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = body if body is not None else []
    resp.headers = {"Link": link} if link else {}
    return resp


def _make_manager(
    *,
    can_resume: bool = False,
    resume_state: GithubResumeConfig | None = None,
) -> mock.Mock:
    manager = mock.Mock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = resume_state
    manager.save_state = mock.Mock()
    return manager


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            ("date", date(2026, 3, 4), "2026-03-04T00:00:00"),
            ("string_passthrough", "some-cursor-value", "some-cursor-value"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestBuildInitialParams:
    def test_defaults_to_asc_created(self) -> None:
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

    def test_incremental_issues_uses_since(self) -> None:
        params = _build_initial_params(
            GITHUB_ENDPOINTS["issues"],
            "issues",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14),
            incremental_field="updated_at",
        )
        assert params["sort"] == "updated"
        assert params["direction"] == "asc"  # issues config sort_mode defaults to asc
        assert params["since"] == "2026-03-04T02:58:14"

    def test_incremental_pull_requests_desc_no_since(self) -> None:
        params = _build_initial_params(
            GITHUB_ENDPOINTS["pull_requests"],
            "pull_requests",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14),
            incremental_field="updated_at",
        )
        assert params["direction"] == "desc"
        # pull_requests doesn't support the 'since' param
        assert "since" not in params


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
            (
                "only_last",
                '<https://api.github.com/x?page=5>; rel="last"',
                None,
            ),
            (
                "with_prev_and_next",
                '<https://api.github.com/x?page=1>; rel="prev", <https://api.github.com/x?page=3>; rel="next"',
                "https://api.github.com/x?page=3",
            ),
        ]
    )
    def test_parse(self, _name: str, header: str, expected: str | None) -> None:
        assert _parse_next_url(header) == expected


class TestIsOlderThanCutoff:
    def setup_method(self) -> None:
        self.cutoff = datetime(2026, 3, 4, 2, 58, 14)

    def test_none(self) -> None:
        assert _is_older_than_cutoff(None, self.cutoff) is False

    def test_string_older(self) -> None:
        assert _is_older_than_cutoff("2026-03-01T00:00:00Z", self.cutoff) is True

    def test_string_newer(self) -> None:
        assert _is_older_than_cutoff("2026-03-10T00:00:00Z", self.cutoff) is False

    def test_invalid_string(self) -> None:
        assert _is_older_than_cutoff("not-a-date", self.cutoff) is False

    def test_datetime_older(self) -> None:
        assert _is_older_than_cutoff(datetime(2025, 1, 1), self.cutoff) is True


class TestShouldStopDesc:
    def test_asc_mode_never_stops(self) -> None:
        assert (
            _should_stop_desc(
                data=[{"updated_at": "2000-01-01T00:00:00Z"}],
                sort_mode="asc",
                incremental_field="updated_at",
                cutoff=datetime(2026, 3, 4),
            )
            is False
        )

    def test_desc_stops_when_old_record_present(self) -> None:
        assert (
            _should_stop_desc(
                data=[{"updated_at": "2026-05-01T00:00:00Z"}, {"updated_at": "2025-01-01T00:00:00Z"}],
                sort_mode="desc",
                incremental_field="updated_at",
                cutoff=datetime(2026, 3, 4),
            )
            is True
        )

    def test_desc_continues_when_all_newer(self) -> None:
        assert (
            _should_stop_desc(
                data=[{"updated_at": "2026-05-01T00:00:00Z"}],
                sort_mode="desc",
                incremental_field="updated_at",
                cutoff=datetime(2026, 3, 4),
            )
            is False
        )


@pytest.fixture
def logger() -> mock.Mock:
    return mock.Mock()


class TestGetRowsResume:
    """Integration tests for the resume flow in get_rows."""

    def _patch_batcher(self):
        """Force the Batcher to yield after every single batched item."""
        return mock.patch(
            "posthog.temporal.data_imports.sources.github.github.Batcher",
            autospec=False,
            side_effect=lambda logger, chunk_size, chunk_size_bytes: _ImmediateBatcher(),
        )

    def test_fresh_run_saves_next_url_after_batch(self, logger: mock.Mock) -> None:
        """First run: manager.can_resume()=False, initial URL is used, save_state called after each yielded chunk."""
        manager = _make_manager(can_resume=False)

        page1_body = [{"id": 1, "updated_at": "2026-01-01T00:00:00Z"}]
        page2_body = [{"id": 2, "updated_at": "2026-01-02T00:00:00Z"}]
        link_page1 = '<https://api.github.com/repos/owner/repo/releases?page=2>; rel="next"'

        responses = [
            _make_response(body=page1_body, link=link_page1),
            _make_response(body=page2_body, link=""),
        ]

        with (
            self._patch_batcher(),
            mock.patch(
                "posthog.temporal.data_imports.sources.github.github.requests.get",
                side_effect=responses,
            ) as mock_get,
        ):
            list(
                get_rows(
                    personal_access_token="tok",
                    repository="owner/repo",
                    endpoint="releases",
                    logger=logger,
                    resumable_source_manager=manager,
                    should_use_incremental_field=False,
                )
            )

        # Initial URL came from our builder — not a saved resume state.
        first_url = mock_get.call_args_list[0].args[0]
        assert first_url.startswith("https://api.github.com/repos/owner/repo/releases")
        manager.load_state.assert_not_called()

        # save_state was called exactly once with page 2 as the next URL.
        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, GithubResumeConfig)
        assert saved.next_url == "https://api.github.com/repos/owner/repo/releases?page=2"

    def test_resume_uses_saved_url(self, logger: mock.Mock) -> None:
        """Resume path: can_resume()=True, load_state returns config, first request is to the saved URL."""
        saved_url = "https://api.github.com/repos/owner/repo/releases?page=4"
        manager = _make_manager(
            can_resume=True,
            resume_state=GithubResumeConfig(next_url=saved_url),
        )

        responses = [_make_response(body=[{"id": 42, "updated_at": "2026-01-01T00:00:00Z"}], link="")]

        with (
            self._patch_batcher(),
            mock.patch(
                "posthog.temporal.data_imports.sources.github.github.requests.get",
                side_effect=responses,
            ) as mock_get,
        ):
            list(
                get_rows(
                    personal_access_token="tok",
                    repository="owner/repo",
                    endpoint="releases",
                    logger=logger,
                    resumable_source_manager=manager,
                    should_use_incremental_field=False,
                )
            )

        assert mock_get.call_args_list[0].args[0] == saved_url
        manager.load_state.assert_called_once()

    def test_empty_first_page_ends_loop(self, logger: mock.Mock) -> None:
        manager = _make_manager(can_resume=False)
        with (
            self._patch_batcher(),
            mock.patch(
                "posthog.temporal.data_imports.sources.github.github.requests.get",
                side_effect=[_make_response(body=[], link="")],
            ),
        ):
            rows = list(
                get_rows(
                    personal_access_token="tok",
                    repository="owner/repo",
                    endpoint="releases",
                    logger=logger,
                    resumable_source_manager=manager,
                    should_use_incremental_field=False,
                )
            )

        assert rows == []
        manager.save_state.assert_not_called()

    def test_final_page_does_not_save_state(self, logger: mock.Mock) -> None:
        """The final page has no Link next header, so save_state is never called."""
        manager = _make_manager(can_resume=False)
        with (
            self._patch_batcher(),
            mock.patch(
                "posthog.temporal.data_imports.sources.github.github.requests.get",
                side_effect=[_make_response(body=[{"id": 1}], link="")],
            ),
        ):
            list(
                get_rows(
                    personal_access_token="tok",
                    repository="owner/repo",
                    endpoint="releases",
                    logger=logger,
                    resumable_source_manager=manager,
                    should_use_incremental_field=False,
                )
            )

        manager.save_state.assert_not_called()


class _ImmediateBatcher:
    """Test double for Batcher that emits every single item as its own chunk.

    Only implements the surface area `get_rows` calls.
    """

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
