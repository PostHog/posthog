from collections.abc import Callable, Iterator
from typing import Any, Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.snapchat_ads.snapchat_ads import SnapchatResumeConfig, _iter_rows


class _FakeResource:
    """Iterable stand-in for a ``rest_api_resource`` that drives ``resume_hook``
    the way the real REST client does: one call per page, with the next-page
    cursor when available and ``None`` after the last page."""

    def __init__(
        self,
        pages: list[list[dict[str, Any]]],
        resume_hook: Optional[Callable[[Optional[dict[str, Any]]], None]],
        next_link_prefix: str = "https://adsapi.snapchat.com/v1/next?cursor=page",
    ) -> None:
        self._pages = pages
        self._resume_hook = resume_hook
        self._next_link_prefix = next_link_prefix

    def __iter__(self) -> Iterator[list[dict[str, Any]]]:
        total = len(self._pages)
        for index, page in enumerate(self._pages):
            yield page
            if self._resume_hook is None:
                continue
            if index < total - 1:
                next_state: Optional[dict[str, Any]] = {"next_link": f"{self._next_link_prefix}{index + 1}"}
            else:
                next_state = None
            self._resume_hook(next_state)


def _mock_resumable_manager(*, can_resume: bool = False, saved: Optional[SnapchatResumeConfig] = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = saved
    return manager


class TestIterRowsFreshRun:
    def test_calls_rest_api_resource_without_initial_state(self) -> None:
        captured_kwargs: dict[str, Any] = {}

        def _fake_rest_api_resource(*args: Any, **kwargs: Any) -> _FakeResource:
            captured_kwargs.update(kwargs)
            return _FakeResource(
                pages=[[{"id": "c1"}], [{"id": "c2"}]],
                resume_hook=kwargs["resume_hook"],
            )

        manager = _mock_resumable_manager(can_resume=False)

        with patch(
            "posthog.temporal.data_imports.sources.snapchat_ads.snapchat_ads.rest_api_resource",
            side_effect=_fake_rest_api_resource,
        ):
            batches = list(
                _iter_rows(
                    ad_account_id="acct",
                    endpoint="campaigns",
                    team_id=1,
                    job_id="job",
                    access_token="token",
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=None,
                    should_use_incremental_field=False,
                )
            )

        assert batches == [[{"id": "c1"}], [{"id": "c2"}]]
        assert captured_kwargs["initial_paginator_state"] is None
        manager.load_state.assert_not_called()

    def test_saves_checkpoint_with_next_link_after_each_page(self) -> None:
        def _fake_rest_api_resource(*args: Any, **kwargs: Any) -> _FakeResource:
            return _FakeResource(
                pages=[[{"id": "c1"}], [{"id": "c2"}], [{"id": "c3"}]],
                resume_hook=kwargs["resume_hook"],
            )

        manager = _mock_resumable_manager(can_resume=False)

        with patch(
            "posthog.temporal.data_imports.sources.snapchat_ads.snapchat_ads.rest_api_resource",
            side_effect=_fake_rest_api_resource,
        ):
            list(
                _iter_rows(
                    ad_account_id="acct",
                    endpoint="campaigns",
                    team_id=1,
                    job_id="job",
                    access_token="token",
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=None,
                    should_use_incremental_field=False,
                )
            )

        saved_configs = [call.args[0] for call in manager.save_state.call_args_list]
        # Only concrete next_link cursors are persisted — the final None call
        # from the resume_hook is a no-op, matching mailchimp/reddit_ads.
        assert saved_configs == [
            SnapchatResumeConfig(
                chunk_index=0,
                next_link="https://adsapi.snapchat.com/v1/next?cursor=page1",
            ),
            SnapchatResumeConfig(
                chunk_index=0,
                next_link="https://adsapi.snapchat.com/v1/next?cursor=page2",
            ),
        ]


class TestIterRowsResume:
    @parameterized.expand(
        [
            (
                "valid_state_seeds_paginator",
                SnapchatResumeConfig(
                    chunk_index=0,
                    next_link="https://adsapi.snapchat.com/v1/campaigns?cursor=page1&limit=1000",
                ),
                {"next_link": "https://adsapi.snapchat.com/v1/campaigns?cursor=page1&limit=1000"},
            ),
            (
                "stale_chunk_index_falls_back_to_start",
                SnapchatResumeConfig(chunk_index=5, next_link="https://example.com/cursor=x"),
                None,
            ),
        ]
    )
    def test_initial_paginator_state_from_resume(
        self,
        _name: str,
        saved: SnapchatResumeConfig,
        expected_initial_state: Optional[dict[str, Any]],
    ) -> None:
        captured_kwargs: dict[str, Any] = {}

        def _fake_rest_api_resource(*args: Any, **kwargs: Any) -> _FakeResource:
            captured_kwargs.update(kwargs)
            return _FakeResource(pages=[[{"id": "c1"}]], resume_hook=kwargs["resume_hook"])

        manager = _mock_resumable_manager(can_resume=True, saved=saved)

        with patch(
            "posthog.temporal.data_imports.sources.snapchat_ads.snapchat_ads.rest_api_resource",
            side_effect=_fake_rest_api_resource,
        ):
            batches = list(
                _iter_rows(
                    ad_account_id="acct",
                    endpoint="campaigns",
                    team_id=1,
                    job_id="job",
                    access_token="token",
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=None,
                    should_use_incremental_field=False,
                )
            )

        assert batches == [[{"id": "c1"}]]
        assert captured_kwargs["initial_paginator_state"] == expected_initial_state


class TestIterRowsEmptyPages:
    def test_empty_pages_are_not_yielded(self) -> None:
        def _fake_rest_api_resource(*args: Any, **kwargs: Any) -> _FakeResource:
            return _FakeResource(pages=[[], [{"id": "c1"}], []], resume_hook=kwargs["resume_hook"])

        manager = _mock_resumable_manager(can_resume=False)

        with patch(
            "posthog.temporal.data_imports.sources.snapchat_ads.snapchat_ads.rest_api_resource",
            side_effect=_fake_rest_api_resource,
        ):
            batches = list(
                _iter_rows(
                    ad_account_id="acct",
                    endpoint="campaigns",
                    team_id=1,
                    job_id="job",
                    access_token="token",
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=None,
                    should_use_incremental_field=False,
                )
            )

        assert batches == [[{"id": "c1"}]]


def _fake_stats_chunks(count: int) -> list[dict[str, Any]]:
    """Stand-in for ``SnapchatStatsResource.setup_stats_resources`` output.

    Only the structural bits ``_build_chunk_resources`` inspects are needed:
    an ``endpoint`` dict that the paginator can be written into.
    """
    return [{"name": f"stats_chunk_{i}", "endpoint": {"path": "/stats"}} for i in range(count)]


def _stats_page(entity_id: str) -> list[dict[str, Any]]:
    """Minimal page payload shaped the way ``transform_stats_reports`` expects."""
    return [
        {
            "timeseries_stat": {
                "id": entity_id,
                "type": "CAMPAIGN",
                "timeseries": [
                    {
                        "start_time": "2026-04-01T00:00:00Z",
                        "end_time": "2026-04-02T00:00:00Z",
                        "stats": {"impressions": 1},
                    }
                ],
            }
        }
    ]


class TestIterRowsMultiChunkStats:
    """STATS endpoints fan out across date chunks; these tests drive
    ``_iter_rows`` through a 2-chunk fake fan-out to exercise chunk
    advancement and resume-across-chunks behavior."""

    def test_fresh_run_iterates_all_chunks_and_advances_checkpoint(self) -> None:
        captured_calls: list[dict[str, Any]] = []

        def _fake_rest_api_resource(*args: Any, **kwargs: Any) -> _FakeResource:
            captured_calls.append(dict(kwargs))
            chunk_idx = len(captured_calls) - 1
            return _FakeResource(
                pages=[_stats_page(f"entity-{chunk_idx}")],
                resume_hook=kwargs["resume_hook"],
                next_link_prefix=f"https://adsapi.snapchat.com/v1/stats?chunk={chunk_idx}&cursor=page",
            )

        manager = _mock_resumable_manager(can_resume=False)

        with (
            patch(
                "posthog.temporal.data_imports.sources.snapchat_ads.snapchat_ads.rest_api_resource",
                side_effect=_fake_rest_api_resource,
            ),
            patch(
                "posthog.temporal.data_imports.sources.snapchat_ads.snapchat_ads.SnapchatStatsResource.setup_stats_resources",
                return_value=_fake_stats_chunks(2),
            ),
            patch(
                "posthog.temporal.data_imports.sources.snapchat_ads.snapchat_ads.fetch_account_currency",
                return_value="USD",
            ),
        ):
            list(
                _iter_rows(
                    ad_account_id="acct",
                    endpoint="campaign_stats_daily",
                    team_id=1,
                    job_id="job",
                    access_token="token",
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=None,
                    should_use_incremental_field=False,
                )
            )

        assert len(captured_calls) == 2
        assert captured_calls[0]["initial_paginator_state"] is None
        assert captured_calls[1]["initial_paginator_state"] is None

        saved_configs = [call.args[0] for call in manager.save_state.call_args_list]
        # The resume_hook only persists concrete cursors, so single-page
        # chunks never trigger a save from the hook. The only persisted
        # state is the explicit advance to chunk_index=1 before chunk 1
        # starts. The last chunk has no successor, so no trailing advance.
        assert saved_configs == [
            SnapchatResumeConfig(chunk_index=1, next_link=None),
        ]

    def test_resume_from_second_chunk_skips_first_and_seeds_cursor(self) -> None:
        captured_calls: list[dict[str, Any]] = []

        def _fake_rest_api_resource(*args: Any, **kwargs: Any) -> _FakeResource:
            captured_calls.append(dict(kwargs))
            return _FakeResource(pages=[_stats_page("entity-resumed")], resume_hook=kwargs["resume_hook"])

        saved = SnapchatResumeConfig(
            chunk_index=1,
            next_link="https://adsapi.snapchat.com/v1/stats?chunk=1&cursor=midchunk",
        )
        manager = _mock_resumable_manager(can_resume=True, saved=saved)

        with (
            patch(
                "posthog.temporal.data_imports.sources.snapchat_ads.snapchat_ads.rest_api_resource",
                side_effect=_fake_rest_api_resource,
            ),
            patch(
                "posthog.temporal.data_imports.sources.snapchat_ads.snapchat_ads.SnapchatStatsResource.setup_stats_resources",
                return_value=_fake_stats_chunks(2),
            ),
            patch(
                "posthog.temporal.data_imports.sources.snapchat_ads.snapchat_ads.fetch_account_currency",
                return_value="USD",
            ),
        ):
            list(
                _iter_rows(
                    ad_account_id="acct",
                    endpoint="campaign_stats_daily",
                    team_id=1,
                    job_id="job",
                    access_token="token",
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=None,
                    should_use_incremental_field=False,
                )
            )

        # The first chunk is skipped entirely — only one rest_api_resource call.
        assert len(captured_calls) == 1
        assert captured_calls[0]["initial_paginator_state"] == {
            "next_link": "https://adsapi.snapchat.com/v1/stats?chunk=1&cursor=midchunk",
        }
