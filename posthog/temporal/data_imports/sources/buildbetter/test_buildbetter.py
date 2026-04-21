from unittest.mock import MagicMock, patch

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
    def test_fresh_run_starts_at_offset_zero_and_saves_state(self) -> None:
        page_size = BUILDBETTER_ENDPOINTS["interviews"].page_size
        first_page = _interview_payload([str(i) for i in range(page_size)])
        second_page = _interview_payload(["last"])

        manager = _make_manager(can_resume=False)
        logger = MagicMock()

        with patch("posthog.temporal.data_imports.sources.buildbetter.buildbetter.requests.Session") as session_cls:
            session = session_cls.return_value
            session.post.side_effect = [
                _make_response(first_page),
                _make_response(second_page),
            ]

            batches = list(
                _make_paginated_request(
                    api_key="key",
                    endpoint_name="interviews",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        assert len(batches) == 2
        assert len(batches[0]) == page_size
        assert batches[1] == [{"id": "last"}]

        # First request starts from offset 0
        first_call = session.post.call_args_list[0]
        assert first_call.kwargs["json"]["variables"]["offset"] == 0

        # Second request picks up after the first full page
        second_call = session.post.call_args_list[1]
        assert second_call.kwargs["json"]["variables"]["offset"] == page_size

        # State is saved after the first (full) page pointing at the next offset,
        # and not again after the final short page (loop exits without advancing).
        manager.save_state.assert_called_once_with(BuildBetterResumeConfig(offset=page_size))

    def test_resume_path_seeds_offset_from_loaded_state(self) -> None:
        page_size = BUILDBETTER_ENDPOINTS["interviews"].page_size
        saved_offset = page_size * 3
        # Single short page ends the loop without saving further state
        resumed_page = _interview_payload(["resumed"])

        manager = _make_manager(can_resume=True, state=BuildBetterResumeConfig(offset=saved_offset))
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

        assert batches == [[{"id": "resumed"}]]

        # Single request issued, starting from the saved offset (no re-fetch of earlier pages)
        assert session.post.call_count == 1
        call = session.post.call_args_list[0]
        assert call.kwargs["json"]["variables"]["offset"] == saved_offset

        manager.can_resume.assert_called_once()
        manager.load_state.assert_called_once()
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
            batches = list(response.items())

        assert batches == [[{"id": "x"}]]
        assert response.primary_keys == ["id"]
        manager.can_resume.assert_called_once()
