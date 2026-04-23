import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from posthog.temporal.data_imports.sources.attio.attio import (
    AttioOffsetPaginator,
    AttioResumeConfig,
    attio_source,
)
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class TestAttioOffsetPaginator:
    def test_initial_state(self) -> None:
        paginator = AttioOffsetPaginator(limit=100)
        assert paginator._limit == 100
        assert paginator._current_offset == 0

    @pytest.mark.parametrize(
        ("label", "seeded_offset", "use_json_body"),
        [
            ("fresh_params", None, False),
            ("resumed_params", 500, False),
            ("fresh_json", None, True),
            ("resumed_json", 500, True),
        ],
    )
    def test_init_request_sets_offset_and_limit(
        self, label: str, seeded_offset: int | None, use_json_body: bool
    ) -> None:
        paginator = AttioOffsetPaginator(limit=100, use_json_body=use_json_body)
        if seeded_offset is not None:
            paginator.set_resume_state({"offset": seeded_offset})

        request = Request(method="POST" if use_json_body else "GET", url="https://api.attio.com/v2/lists")
        paginator.init_request(request)

        expected_offset = seeded_offset if seeded_offset is not None else 0
        if use_json_body:
            assert request.json is not None
            assert request.json["offset"] == expected_offset
            assert request.json["limit"] == 100
        else:
            assert request.params is not None
            assert request.params["offset"] == expected_offset
            assert request.params["limit"] == 100

    def test_update_state_full_page_has_next(self) -> None:
        paginator = AttioOffsetPaginator(limit=2)
        response = MagicMock()
        response.json.return_value = {"data": [{"a": 1}, {"b": 2}]}
        paginator.update_state(response)
        assert paginator._has_next_page is True
        assert paginator._next_offset == 2

    def test_update_state_partial_page_no_next(self) -> None:
        paginator = AttioOffsetPaginator(limit=2)
        response = MagicMock()
        response.json.return_value = {"data": [{"a": 1}]}
        paginator.update_state(response)
        assert paginator._has_next_page is False
        assert paginator._next_offset is None

    def test_update_request_advances_offset(self) -> None:
        paginator = AttioOffsetPaginator(limit=100)
        response = MagicMock()
        response.json.return_value = {"data": [{} for _ in range(100)]}
        paginator.update_state(response)

        request = Request(method="GET", url="https://api.attio.com/v2/lists", params={})
        paginator.update_request(request)

        assert paginator._current_offset == 100
        assert request.params is not None
        assert request.params["offset"] == 100

    def test_get_resume_state_returns_current_offset_after_advance(self) -> None:
        paginator = AttioOffsetPaginator(limit=100)
        response = MagicMock()
        response.json.return_value = {"data": [{} for _ in range(100)]}
        paginator.update_state(response)
        paginator.update_request(Request(method="GET", url="x"))

        assert paginator.get_resume_state() == {"offset": 100}

    def test_set_resume_state_round_trip(self) -> None:
        paginator = AttioOffsetPaginator(limit=100)
        paginator.set_resume_state({"offset": 500})

        assert paginator._current_offset == 500
        assert paginator.has_next_page is True
        assert paginator.get_resume_state() == {"offset": 500}

    def test_set_resume_state_ignores_missing_offset(self) -> None:
        paginator = AttioOffsetPaginator(limit=100)
        paginator.set_resume_state({})

        assert paginator._current_offset == 0


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestAttioSourceResumeBehavior:
    """End-to-end resume behaviour of ``attio_source`` through the shared
    ``rest_api_resource`` path. Drives the source against a mocked HTTP
    session so we can observe what params/JSON were actually sent and which
    checkpoints were saved."""

    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
    ) -> tuple[list[dict[str, Any] | None], list[dict[str, Any] | None]]:
        """Drive ``attio_source`` and capture request state per page.

        Returns ``(sent_params, sent_json)`` snapshotted at send-time — the
        Request object is mutated in-place by the paginator between pages,
        so we can't rely on mock ``call_args_list`` to preserve history.
        """
        sent_params: list[dict[str, Any] | None] = []
        sent_json: list[dict[str, Any] | None] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params) if request.params else None)
            sent_json.append(dict(request.json) if request.json else None)
            return next(response_iter)

        with patch(
            "posthog.temporal.data_imports.sources.common.rest_source.rest_client.requests.Session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            response = attio_source(
                api_key="attio_key",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )
            list(cast(Iterable[Any], response.items()))
            return sent_params, sent_json

    def test_get_endpoint_fresh_run_saves_offset_after_each_non_terminal_page(self) -> None:
        """``lists`` is a GET endpoint — pagination lives in query params."""
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        # page_size for lists is 500 (see settings.py). Use three full-size
        # pages plus a short final page so the paginator terminates naturally.
        page = [{"id": {"list_id": f"l{i}"}} for i in range(500)]
        short_page = [{"id": {"list_id": "final"}}]
        responses = [
            _make_http_response({"data": page}),
            _make_http_response({"data": page}),
            _make_http_response({"data": short_page}),
        ]
        sent_params, _ = self._drive("lists", manager, responses)

        assert [p["offset"] for p in sent_params if p is not None] == [0, 500, 1000]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            AttioResumeConfig(offset=500),
            AttioResumeConfig(offset=1000),
        ]

    def test_get_endpoint_resume_seeds_paginator_with_saved_offset(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = AttioResumeConfig(offset=1000)

        # One short page — resume → one fetch at offset=1000, then terminate.
        responses = [_make_http_response({"data": [{"id": {"list_id": "final"}}]})]
        sent_params, _ = self._drive("lists", manager, responses)

        assert sent_params[0] is not None
        assert sent_params[0]["offset"] == 1000
        # Resumed into the final page, so no further checkpoint is needed.
        manager.save_state.assert_not_called()

    def test_post_endpoint_fresh_run_paginates_via_json_body(self) -> None:
        """``companies`` is a POST endpoint — pagination lives in the JSON body."""
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        page = [{"id": {"record_id": f"r{i}"}} for i in range(500)]
        short_page = [{"id": {"record_id": "final"}}]
        responses = [
            _make_http_response({"data": page}),
            _make_http_response({"data": short_page}),
        ]
        _, sent_json = self._drive("companies", manager, responses)

        assert [j["offset"] for j in sent_json if j is not None] == [0, 500]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [AttioResumeConfig(offset=500)]

    def test_post_endpoint_resume_uses_saved_offset_in_json_body(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = AttioResumeConfig(offset=500)

        responses = [_make_http_response({"data": [{"id": {"record_id": "final"}}]})]
        _, sent_json = self._drive("companies", manager, responses)

        assert sent_json[0] is not None
        assert sent_json[0]["offset"] == 500
        # The sort clause from the endpoint config must still be included on resume.
        assert sent_json[0]["sorts"] == [{"attribute": "created_at", "direction": "asc"}]
        manager.save_state.assert_not_called()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"data": [{"id": {"list_id": "only"}}]})]
        self._drive("lists", manager, responses)

        manager.save_state.assert_not_called()

    def test_saved_state_with_zero_offset_is_ignored(self) -> None:
        # A zero-offset checkpoint is equivalent to a fresh run — don't seed.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = AttioResumeConfig(offset=0)

        responses = [_make_http_response({"data": [{"id": {"list_id": "a"}}]})]
        sent_params, _ = self._drive("lists", manager, responses)

        assert sent_params[0] is not None
        assert sent_params[0]["offset"] == 0

    def test_empty_response_terminates_without_saving(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"data": []})]
        self._drive("lists", manager, responses)

        manager.save_state.assert_not_called()

    def test_saved_state_serialization_round_trip(self) -> None:
        # Ensure ResumableSourceManager's asdict/json round trip reproduces
        # the dataclass unchanged.
        import dataclasses

        cfg = AttioResumeConfig(offset=1500)
        as_json = json.dumps(dataclasses.asdict(cfg))
        reconstituted = AttioResumeConfig(**json.loads(as_json))
        assert reconstituted == cfg
