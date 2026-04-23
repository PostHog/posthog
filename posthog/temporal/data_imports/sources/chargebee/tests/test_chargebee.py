import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from posthog.temporal.data_imports.sources.chargebee.chargebee import (
    ChargebeePaginator,
    ChargebeeResumeConfig,
    chargebee_source,
)
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class TestChargebeePaginator:
    def test_initial_state(self) -> None:
        paginator = ChargebeePaginator()
        assert paginator._next_offset is None
        # BasePaginator starts with _has_next_page=True so the first request runs;
        # update_state flips it to False on the terminal page.
        assert paginator.has_next_page is True

    def test_update_state_has_more(self) -> None:
        paginator = ChargebeePaginator()
        response = MagicMock()
        response.json.return_value = {"list": [{"customer": {"id": "c1"}}], "next_offset": "cursor-1"}
        paginator.update_state(response)
        assert paginator._next_offset == "cursor-1"
        assert paginator.has_next_page is True

    def test_update_state_no_more(self) -> None:
        paginator = ChargebeePaginator()
        response = MagicMock()
        response.json.return_value = {"list": [{"customer": {"id": "c1"}}]}
        paginator.update_state(response)
        assert paginator._next_offset is None
        assert paginator.has_next_page is False

    def test_update_state_empty_body(self) -> None:
        paginator = ChargebeePaginator()
        response = MagicMock()
        response.json.return_value = {}
        paginator.update_state(response)
        assert paginator._next_offset is None
        assert paginator.has_next_page is False

    @pytest.mark.parametrize(
        ("label", "seeded_offset"),
        [
            ("fresh", None),
            ("resumed", "cursor-2000"),
        ],
    )
    def test_init_request_honours_seeded_offset(self, label: str, seeded_offset: str | None) -> None:
        paginator = ChargebeePaginator()
        if seeded_offset is not None:
            paginator.set_resume_state({"next_offset": seeded_offset})

        request = Request(method="GET", url="https://site.chargebee.com/api/v2/customers")
        paginator.init_request(request)

        if seeded_offset is None:
            # A fresh paginator must not inject an offset on the first request.
            assert request.params is None or "offset" not in request.params
        else:
            assert request.params["offset"] == seeded_offset

    def test_get_resume_state_returns_state_when_next_page(self) -> None:
        paginator = ChargebeePaginator()
        response = MagicMock()
        response.json.return_value = {"next_offset": "cursor-42"}
        paginator.update_state(response)

        assert paginator.get_resume_state() == {"next_offset": "cursor-42"}

    def test_get_resume_state_returns_none_on_terminal_page(self) -> None:
        paginator = ChargebeePaginator()
        response = MagicMock()
        response.json.return_value = {"list": []}
        paginator.update_state(response)

        assert paginator.get_resume_state() is None

    def test_set_resume_state_round_trip(self) -> None:
        paginator = ChargebeePaginator()
        paginator.set_resume_state({"next_offset": "cursor-99"})

        assert paginator._next_offset == "cursor-99"
        assert paginator.has_next_page is True
        assert paginator.get_resume_state() == {"next_offset": "cursor-99"}

    def test_set_resume_state_coerces_to_string(self) -> None:
        # Chargebee cursors come back as strings in live responses, but defensive casting
        # protects against a Redis round-trip that somehow returns a number.
        paginator = ChargebeePaginator()
        paginator.set_resume_state({"next_offset": 12345})

        assert paginator._next_offset == "12345"
        assert paginator.has_next_page is True

    def test_set_resume_state_ignores_missing_offset(self) -> None:
        paginator = ChargebeePaginator()
        paginator.set_resume_state({})

        assert paginator._next_offset is None
        # has_next_page is left at its BasePaginator default (True) so a fresh run still fires the first request.


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestChargebeeSourceResumeBehavior:
    """End-to-end resume behaviour of ``chargebee_source`` via ``rest_api_resource``."""

    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response]
    ) -> tuple[MagicMock, list[dict[str, Any]]]:
        """Drive ``chargebee_source`` with a mocked HTTP session.

        Returns ``(mock_session, sent_params)`` where ``sent_params`` is a list
        of shallow copies of ``request.params`` captured at send-time — the
        underlying Request object is mutated in-place by the paginator between
        pages, so we can't rely on mock ``call_args_list`` to preserve history.
        """
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with patch(
            "posthog.temporal.data_imports.sources.common.rest_source.rest_client.requests.Session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            resource = chargebee_source(
                api_key="test-key",
                site_name="site-test",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=None,
                should_use_incremental_field=False,
            )
            list(cast(Iterable[Any], resource))
            return mock_session, sent_params

    @pytest.mark.parametrize("endpoint", ["Customers", "Events", "Invoices", "Subscriptions", "Transactions", "Orders"])
    def test_fresh_run_saves_offset_after_each_non_terminal_page(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        # Three pages: two with next_offset (intermediate), one terminal. Selector
        # is a list under "list" — match chargebee's actual response shape.
        responses = [
            _make_http_response({"list": [{"customer": {"id": "c1"}}], "next_offset": "cursor-1"}),
            _make_http_response({"list": [{"customer": {"id": "c2"}}], "next_offset": "cursor-2"}),
            _make_http_response({"list": [{"customer": {"id": "c3"}}]}),
        ]
        _, sent_params = self._drive(endpoint, manager, responses)

        # First request has no offset (fresh run); subsequent requests carry the prior page's cursor.
        offsets_sent = [p.get("offset") for p in sent_params]
        assert offsets_sent == [None, "cursor-1", "cursor-2"]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            ChargebeeResumeConfig(next_offset="cursor-1"),
            ChargebeeResumeConfig(next_offset="cursor-2"),
        ]

    def test_resume_seeds_paginator_with_saved_offset(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = ChargebeeResumeConfig(next_offset="cursor-resumed")

        responses = [
            _make_http_response({"list": [{"customer": {"id": "c4"}}]}),
        ]
        _, sent_params = self._drive("Customers", manager, responses)

        assert [p.get("offset") for p in sent_params] == ["cursor-resumed"]
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response({"list": [{"customer": {"id": "only"}}]}),
        ]
        self._drive("Customers", manager, responses)

        manager.save_state.assert_not_called()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response({"list": [{"customer": {"id": "a"}}]}),
        ]
        self._drive("Customers", manager, responses)

        manager.load_state.assert_not_called()
