from collections.abc import Iterable
from typing import Any, cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.data_imports.sources.buildbetter.buildbetter import (
    BuildBetterResumeConfig,
    _make_paginated_request,
    buildbetter_source,
)
from posthog.temporal.data_imports.sources.buildbetter.settings import BUILDBETTER_ENDPOINTS
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager


def _make_response(json_data: dict, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = json_data
    return response


def _make_manager(can_resume: bool = False, state: BuildBetterResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


def _interview_payload(ids: list[str]) -> dict:
    return {"data": {"interview": [{"id": i} for i in ids]}}


class TestMakePaginatedRequest:
    @parameterized.expand(
        [
            ("fresh_run", False, None, 0),
            ("resume", True, 3, 3),
        ]
    )
    def test_starting_offset_from_resume_state(
        self,
        _name: str,
        can_resume: bool,
        saved_offset_multiplier: int | None,
        expected_first_offset_multiplier: int,
    ) -> None:
        page_size = BUILDBETTER_ENDPOINTS["interviews"].page_size
        saved_offset = saved_offset_multiplier * page_size if saved_offset_multiplier is not None else None
        expected_first_offset = expected_first_offset_multiplier * page_size
        # Single short page terminates the loop without saving further state
        resumed_page = _interview_payload(["x"])

        state = BuildBetterResumeConfig(offset=saved_offset) if saved_offset is not None else None
        manager = _make_manager(can_resume=can_resume, state=state)
        logger = MagicMock()

        with patch("posthog.temporal.data_imports.sources.buildbetter.buildbetter.requests.Session") as session_cls:
            session = session_cls.return_value
            session.post.return_value = _make_response(resumed_page)

            batches = list(
                _make_paginated_request(
                    api_key="key",
                    endpoint_name="interviews",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        assert batches == [[{"id": "x"}]]
        assert session.post.call_count == 1
        call = session.post.call_args_list[0]
        assert call.kwargs["json"]["variables"]["offset"] == expected_first_offset

        manager.can_resume.assert_called_once()
        if can_resume:
            manager.load_state.assert_called_once()
        else:
            manager.load_state.assert_not_called()
        # Short page terminates the loop; save_state is not invoked
        manager.save_state.assert_not_called()

    def test_empty_first_page_does_not_save_state(self) -> None:
        manager = _make_manager(can_resume=False)
        logger = MagicMock()

        with patch("posthog.temporal.data_imports.sources.buildbetter.buildbetter.requests.Session") as session_cls:
            session = session_cls.return_value
            session.post.return_value = _make_response({"data": {"interview": []}})

            batches = list(
                _make_paginated_request(
                    api_key="key",
                    endpoint_name="interviews",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        assert batches == []
        manager.save_state.assert_not_called()

    def test_save_state_called_for_each_full_page(self) -> None:
        page_size = BUILDBETTER_ENDPOINTS["interviews"].page_size
        full_page_a = _interview_payload([f"a{i}" for i in range(page_size)])
        full_page_b = _interview_payload([f"b{i}" for i in range(page_size)])
        tail_page = _interview_payload(["c0"])

        manager = _make_manager(can_resume=False)
        logger = MagicMock()

        with patch("posthog.temporal.data_imports.sources.buildbetter.buildbetter.requests.Session") as session_cls:
            session = session_cls.return_value
            session.post.side_effect = [
                _make_response(full_page_a),
                _make_response(full_page_b),
                _make_response(tail_page),
            ]

            list(
                _make_paginated_request(
                    api_key="key",
                    endpoint_name="interviews",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        saved_offsets = [call.args[0].offset for call in manager.save_state.call_args_list]
        assert saved_offsets == [page_size, page_size * 2]

    def test_incremental_filter_passes_where_clause(self) -> None:
        manager = _make_manager(can_resume=False)
        logger = MagicMock()

        with patch("posthog.temporal.data_imports.sources.buildbetter.buildbetter.requests.Session") as session_cls:
            session = session_cls.return_value
            session.post.return_value = _make_response({"data": {"interview": []}})

            list(
                _make_paginated_request(
                    api_key="key",
                    endpoint_name="interviews",
                    logger=logger,
                    resumable_source_manager=manager,
                    incremental_field="updated_at",
                    incremental_field_last_value="2026-01-01",
                )
            )

        call = session.post.call_args_list[0]
        assert call.kwargs["json"]["variables"]["where"] == {"updated_at": {"_gt": "2026-01-01"}}


class TestBuildbetterSource:
    def test_source_threads_resumable_manager_through(self) -> None:
        manager = _make_manager(can_resume=False)
        logger = MagicMock()

        with patch("posthog.temporal.data_imports.sources.buildbetter.buildbetter.requests.Session") as session_cls:
            session = session_cls.return_value
            session.post.return_value = _make_response(_interview_payload(["x"]))

            response = buildbetter_source(
                api_key="key",
                endpoint_name="interviews",
                logger=logger,
                resumable_source_manager=manager,
            )
            batches = list(cast(Iterable[Any], response.items()))

        assert batches == [[{"id": "x"}]]
        assert response.primary_keys == ["id"]
        manager.can_resume.assert_called_once()
