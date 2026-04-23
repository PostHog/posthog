import json
from typing import Any

import pytest
from unittest import mock

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.meta_ads.meta_ads import (
    MetaAdsResumeConfig,
    _iter_simple_pagination,
    _iter_time_range_pagination,
    _strip_access_token,
)


def _mock_response(status: int, body: dict) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status
    response.json.return_value = body
    response.text = ""
    return response


def _build_manager(*, can_resume: bool = False, state: MetaAdsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


class TestStripAccessToken:
    @pytest.mark.parametrize(
        "url,expected",
        [
            (
                "https://graph.facebook.com/v20/next?access_token=secret&cursor=abc",
                "https://graph.facebook.com/v20/next?cursor=abc",
            ),
            (
                "https://graph.facebook.com/v20/next?cursor=abc&access_token=secret",
                "https://graph.facebook.com/v20/next?cursor=abc",
            ),
            (
                "https://graph.facebook.com/v20/next?access_token=secret",
                "https://graph.facebook.com/v20/next",
            ),
            (
                "https://graph.facebook.com/v20/next?cursor=abc",
                "https://graph.facebook.com/v20/next?cursor=abc",
            ),
            (
                "https://graph.facebook.com/v20/next",
                "https://graph.facebook.com/v20/next",
            ),
            (
                # Multiple access_token params (pathological) — all removed.
                "https://example/path?access_token=a&foo=1&access_token=b",
                "https://example/path?foo=1",
            ),
        ],
    )
    def test_strips(self, url: str, expected: str) -> None:
        assert _strip_access_token(url) == expected


class TestSimplePagination:
    INITIAL_URL = "https://graph.facebook.com/v20/act_123/campaigns"
    INITIAL_PARAMS: dict[str, Any] = {"fields": "id,name", "access_token": "tok"}

    def test_fresh_run_fetches_initial_and_saves_next_url(self) -> None:
        manager = _build_manager()

        responses = [
            _mock_response(
                200,
                {
                    "data": [{"id": "1"}, {"id": "2"}],
                    "paging": {"next": "https://graph.facebook.com/v20/next?access_token=tok&cursor=abc"},
                },
            ),
            _mock_response(200, {"data": [{"id": "3"}], "paging": {}}),
        ]

        with mock.patch("requests.get", side_effect=responses) as mock_get:
            batches = list(
                _iter_simple_pagination(
                    self.INITIAL_URL,
                    self.INITIAL_PARAMS,
                    None,
                    manager,
                )
            )

        assert batches == [[{"id": "1"}, {"id": "2"}], [{"id": "3"}]]
        # First call: initial URL + params.
        assert mock_get.call_args_list[0].args[0] == self.INITIAL_URL
        assert mock_get.call_args_list[0].kwargs["params"] == self.INITIAL_PARAMS
        # Second call: the saved (token-stripped) URL plus access_token supplied via params.
        # Using the stripped URL for the fetch too prevents `requests` from sending duplicate
        # `access_token` query parameters.
        assert mock_get.call_args_list[1].args[0] == "https://graph.facebook.com/v20/next?cursor=abc"
        assert mock_get.call_args_list[1].kwargs["params"] == {"access_token": "tok"}

        # Saved state: access_token stripped from the saved URL.
        manager.save_state.assert_called_once_with(
            MetaAdsResumeConfig(next_url="https://graph.facebook.com/v20/next?cursor=abc")
        )

    def test_resume_skips_initial_request(self) -> None:
        # Saved URL has access_token stripped; we re-inject a fresh one at request time.
        saved_url = "https://graph.facebook.com/v20/next?cursor=xyz"
        manager = _build_manager(can_resume=True, state=MetaAdsResumeConfig(next_url=saved_url))

        responses = [
            _mock_response(200, {"data": [{"id": "5"}], "paging": {}}),
        ]

        with mock.patch("requests.get", side_effect=responses) as mock_get:
            batches = list(
                _iter_simple_pagination(
                    self.INITIAL_URL,
                    self.INITIAL_PARAMS,
                    MetaAdsResumeConfig(next_url=saved_url),
                    manager,
                )
            )

        assert batches == [[{"id": "5"}]]
        assert mock_get.call_count == 1
        assert mock_get.call_args_list[0].args[0] == saved_url
        # access_token is supplied via params (from config), NOT embedded in the saved URL.
        assert mock_get.call_args_list[0].kwargs["params"] == {"access_token": "tok"}
        # No more pages, no save call needed.
        manager.save_state.assert_not_called()

    def test_single_page_does_not_save_state(self) -> None:
        manager = _build_manager()

        responses = [
            _mock_response(200, {"data": [{"id": "1"}], "paging": {}}),
        ]

        with mock.patch("requests.get", side_effect=responses):
            batches = list(
                _iter_simple_pagination(
                    self.INITIAL_URL,
                    {"access_token": "tok"},
                    None,
                    manager,
                )
            )

        assert batches == [[{"id": "1"}]]
        manager.save_state.assert_not_called()

    def test_ignores_resume_state_when_time_range_mode(self) -> None:
        # A time-range-mode state (end_date set) should NOT be consumed by simple pagination.
        manager = _build_manager()
        stale_state = MetaAdsResumeConfig(
            next_url="https://example/ignored",
            end_date="2026-01-01",
            chunk_since="2025-12-15",
            chunk_size_days=30,
        )

        responses = [_mock_response(200, {"data": [], "paging": {}})]

        with mock.patch("requests.get", side_effect=responses) as mock_get:
            list(
                _iter_simple_pagination(
                    self.INITIAL_URL,
                    {"access_token": "tok"},
                    stale_state,
                    manager,
                )
            )

        # Initial request should be the original URL with params, not the stale next_url.
        assert mock_get.call_args_list[0].args[0] == self.INITIAL_URL
        assert mock_get.call_args_list[0].kwargs["params"] == {"access_token": "tok"}


class TestTimeRangePagination:
    URL = "https://graph.facebook.com/v20/act_1/insights"
    PARAMS: dict[str, Any] = {"fields": "ad_id", "limit": 500, "level": "ad", "access_token": "tok"}

    def test_fresh_run_saves_chunk_state_after_first_page(self) -> None:
        manager = _build_manager()
        # One 1-day window (since == until), one page with a paging.next, then done.
        responses = [
            _mock_response(
                200,
                {
                    "data": [{"ad_id": "a"}],
                    "paging": {"next": "https://graph.facebook.com/v20/act_1/insights?access_token=tok&after=abc"},
                },
            ),
            _mock_response(200, {"data": [{"ad_id": "b"}], "paging": {}}),
        ]

        with mock.patch("requests.get", side_effect=responses) as mock_get:
            batches = list(
                _iter_time_range_pagination(
                    self.URL,
                    self.PARAMS,
                    {"since": "2026-04-21", "until": "2026-04-21"},
                    None,
                    manager,
                )
            )

        assert batches == [[{"ad_id": "a"}], [{"ad_id": "b"}]]
        # Two saves: mid-chunk next_url, then the chunk-boundary (past end_date) save.
        assert manager.save_state.call_count == 2
        mid_chunk: MetaAdsResumeConfig = manager.save_state.call_args_list[0].args[0]
        assert mid_chunk.end_date == "2026-04-21"
        assert mid_chunk.chunk_since == "2026-04-21"
        assert mid_chunk.chunk_size_days == 30
        # Saved URL has access_token stripped.
        assert mid_chunk.chunk_next_url == "https://graph.facebook.com/v20/act_1/insights?after=abc"

        final: MetaAdsResumeConfig = manager.save_state.call_args_list[1].args[0]
        assert final.chunk_since == "2026-04-22"
        assert final.chunk_next_url is None

        # Second request uses the stripped URL plus access_token via params (no duplicate token).
        assert mock_get.call_args_list[1].args[0] == "https://graph.facebook.com/v20/act_1/insights?after=abc"
        assert mock_get.call_args_list[1].kwargs["params"] == {"access_token": "tok"}

    def test_fresh_run_saves_chunk_boundary_between_chunks(self) -> None:
        manager = _build_manager()
        # Two 30-day chunks back to back, each with one page.
        responses = [
            _mock_response(200, {"data": [{"ad_id": "a"}], "paging": {}}),
            _mock_response(200, {"data": [{"ad_id": "b"}], "paging": {}}),
        ]

        with mock.patch("requests.get", side_effect=responses):
            batches = list(
                _iter_time_range_pagination(
                    self.URL,
                    self.PARAMS,
                    {"since": "2026-03-01", "until": "2026-04-29"},
                    None,
                    manager,
                )
            )

        assert batches == [[{"ad_id": "a"}], [{"ad_id": "b"}]]
        # After chunk 1 we save pointing at chunk 2; after chunk 2 we save the past-end cursor.
        assert manager.save_state.call_count == 2
        first: MetaAdsResumeConfig = manager.save_state.call_args_list[0].args[0]
        assert first.end_date == "2026-04-29"
        assert first.chunk_since == "2026-03-31"  # chunk 1 covered 2026-03-01..2026-03-30 (30 days)
        assert first.chunk_size_days == 30
        assert first.chunk_next_url is None

        final: MetaAdsResumeConfig = manager.save_state.call_args_list[1].args[0]
        assert final.chunk_since == "2026-04-30"  # one past end_date
        assert final.chunk_next_url is None

    def test_past_end_date_chunk_saved_after_final_chunk(self) -> None:
        """After the final chunk completes, we must save a chunk-boundary cursor
        with ``chunk_since > end_date`` — otherwise a stale mid-chunk next_url
        from an earlier iteration (or no state at all) could cause a resume to
        re-process pages that were already yielded."""
        manager = _build_manager()
        responses = [_mock_response(200, {"data": [{"ad_id": "only"}], "paging": {}})]

        with mock.patch("requests.get", side_effect=responses):
            list(
                _iter_time_range_pagination(
                    self.URL, self.PARAMS, {"since": "2026-04-21", "until": "2026-04-21"}, None, manager
                )
            )

        assert manager.save_state.call_count == 1
        saved: MetaAdsResumeConfig = manager.save_state.call_args_list[0].args[0]
        assert saved.chunk_since == "2026-04-22"
        assert saved.chunk_next_url is None

    def test_resume_past_end_date_cursor_is_noop(self) -> None:
        """If resume state already says ``chunk_since > end_date``, the generator
        must finish without issuing any HTTP request (the sync already ran to
        completion before the crash)."""
        state = MetaAdsResumeConfig(
            end_date="2026-04-21",
            chunk_since="2026-04-22",
            chunk_size_days=30,
            chunk_next_url=None,
        )
        manager = _build_manager(can_resume=True, state=state)

        with mock.patch("requests.get") as mock_get:
            batches = list(
                _iter_time_range_pagination(
                    self.URL, self.PARAMS, {"since": "2026-04-10", "until": "2026-04-21"}, state, manager
                )
            )

        assert batches == []
        mock_get.assert_not_called()

    def test_resume_mid_chunk_skips_initial_request(self) -> None:
        saved_next = "https://graph.facebook.com/v20/act_1/insights?after=xyz"
        # End date matches the end of the resumed chunk so no further chunks are fetched.
        state = MetaAdsResumeConfig(
            end_date="2026-04-16",
            chunk_since="2026-04-10",
            chunk_size_days=7,
            chunk_next_url=saved_next,
        )
        manager = _build_manager(can_resume=True, state=state)

        responses = [_mock_response(200, {"data": [{"ad_id": "c"}], "paging": {}})]

        with mock.patch("requests.get", side_effect=responses) as mock_get:
            batches = list(
                _iter_time_range_pagination(
                    self.URL, self.PARAMS, {"since": "2026-01-01", "until": "2026-04-16"}, state, manager
                )
            )

        assert batches == [[{"ad_id": "c"}]]
        # Two requests: the resumed mid-chunk URL, then nothing more to fetch within this chunk.
        # (There is a final "past end_date" save_state, but no additional HTTP call is made.)
        assert mock_get.call_count == 1
        assert mock_get.call_args_list[0].args[0] == saved_next
        # access_token is injected fresh — never served from the saved URL.
        assert mock_get.call_args_list[0].kwargs["params"] == {"access_token": "tok"}

    def test_resume_at_chunk_boundary_issues_fresh_initial_request(self) -> None:
        state = MetaAdsResumeConfig(
            end_date="2026-04-21",
            chunk_since="2026-04-10",
            chunk_size_days=7,
            chunk_next_url=None,
        )
        manager = _build_manager(can_resume=True, state=state)

        responses = [
            _mock_response(200, {"data": [{"ad_id": "d"}], "paging": {}}),
            _mock_response(200, {"data": [], "paging": {}}),
        ]

        with mock.patch("requests.get", side_effect=responses) as mock_get:
            list(
                _iter_time_range_pagination(
                    self.URL, self.PARAMS, {"since": "2026-01-01", "until": "2026-04-21"}, state, manager
                )
            )

        # First request must be a fresh initial with params embedding the chunk time_range.
        first_call = mock_get.call_args_list[0]
        assert first_call.args[0] == self.URL
        sent_params = first_call.kwargs["params"]
        assert sent_params["access_token"] == "tok"
        # time_range should be JSON-encoded and cover 2026-04-10..2026-04-16 (7 days).
        tr = json.loads(sent_params["time_range"])
        assert tr == {"since": "2026-04-10", "until": "2026-04-16"}

    def test_empty_chunk_still_iterates_to_next(self) -> None:
        manager = _build_manager()
        responses = [
            _mock_response(200, {"data": [], "paging": {}}),
            _mock_response(200, {"data": [{"ad_id": "x"}], "paging": {}}),
        ]

        with mock.patch("requests.get", side_effect=responses):
            batches = list(
                _iter_time_range_pagination(
                    self.URL,
                    self.PARAMS,
                    {"since": "2026-03-01", "until": "2026-04-29"},
                    None,
                    manager,
                )
            )

        assert batches == [[], [{"ad_id": "x"}]]

    def test_timeout_fallback_shrinks_chunk_size(self) -> None:
        manager = _build_manager()
        timeout_body = {"error": {"error_subcode": 1504018, "message": "timeout"}}
        # 30-day chunk times out, then 7-day chunks succeed.
        # 2026-03-01..2026-03-30 is one 30-day attempt that fails.
        # After fallback: 7-day chunks: 03-01..03-07, 03-08..03-14, 03-15..03-21, 03-22..03-28, 03-29..03-30.
        responses = [
            _mock_response(500, timeout_body),
            _mock_response(200, {"data": [{"ad_id": "1"}], "paging": {}}),
            _mock_response(200, {"data": [{"ad_id": "2"}], "paging": {}}),
            _mock_response(200, {"data": [{"ad_id": "3"}], "paging": {}}),
            _mock_response(200, {"data": [{"ad_id": "4"}], "paging": {}}),
            _mock_response(200, {"data": [{"ad_id": "5"}], "paging": {}}),
        ]

        with mock.patch("requests.get", side_effect=responses) as mock_get:
            batches = list(
                _iter_time_range_pagination(
                    self.URL, self.PARAMS, {"since": "2026-03-01", "until": "2026-03-30"}, None, manager
                )
            )

        assert [b[0]["ad_id"] for b in batches] == ["1", "2", "3", "4", "5"]
        # Subsequent saves should all record chunk_size_days=7.
        for call in manager.save_state.call_args_list:
            saved: MetaAdsResumeConfig = call.args[0]
            assert saved.chunk_size_days == 7
        # The first successful request was for a 7-day chunk.
        tr = json.loads(mock_get.call_args_list[1].kwargs["params"]["time_range"])
        assert tr == {"since": "2026-03-01", "until": "2026-03-07"}
