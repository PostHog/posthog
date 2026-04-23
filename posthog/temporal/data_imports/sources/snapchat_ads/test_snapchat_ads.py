from collections.abc import Callable, Iterator
from typing import Any, Optional

from unittest.mock import MagicMock, patch

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
    ) -> None:
        self._pages = pages
        self._resume_hook = resume_hook

    def __iter__(self) -> Iterator[list[dict[str, Any]]]:
        total = len(self._pages)
        for index, page in enumerate(self._pages):
            yield page
            if self._resume_hook is None:
                continue
            if index < total - 1:
                next_state: Optional[dict[str, Any]] = {
                    "next_link": f"https://adsapi.snapchat.com/v1/next?cursor=page{index + 1}"
                }
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
                pages=[[{"id": "c1"}], [{"id": "c2"}]],
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
        assert saved_configs == [
            SnapchatResumeConfig(
                chunk_index=0,
                next_link="https://adsapi.snapchat.com/v1/next?cursor=page1",
            ),
            SnapchatResumeConfig(chunk_index=0, next_link=None),
        ]


class TestIterRowsResume:
    def test_seeds_paginator_from_saved_state(self) -> None:
        captured_kwargs: dict[str, Any] = {}

        def _fake_rest_api_resource(*args: Any, **kwargs: Any) -> _FakeResource:
            captured_kwargs.update(kwargs)
            return _FakeResource(pages=[[{"id": "c2"}]], resume_hook=kwargs["resume_hook"])

        saved = SnapchatResumeConfig(
            chunk_index=0,
            next_link="https://adsapi.snapchat.com/v1/campaigns?cursor=page1&limit=1000",
        )
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

        assert batches == [[{"id": "c2"}]]
        assert captured_kwargs["initial_paginator_state"] == {
            "next_link": "https://adsapi.snapchat.com/v1/campaigns?cursor=page1&limit=1000",
        }

    def test_stale_chunk_index_falls_back_to_start(self) -> None:
        captured_kwargs: dict[str, Any] = {}

        def _fake_rest_api_resource(*args: Any, **kwargs: Any) -> _FakeResource:
            captured_kwargs.update(kwargs)
            return _FakeResource(pages=[[{"id": "c1"}]], resume_hook=kwargs["resume_hook"])

        # campaigns has one chunk; chunk_index=5 is stale relative to the
        # current layout and must not be honored.
        saved = SnapchatResumeConfig(chunk_index=5, next_link="https://example.com/cursor=x")
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
        assert captured_kwargs["initial_paginator_state"] is None


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
