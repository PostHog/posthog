import json
import dataclasses
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from posthog.temporal.data_imports.sources.clerk.clerk import ClerkPaginator, ClerkResumeConfig, clerk_source
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class TestClerkPaginator:
    def test_initial_state(self) -> None:
        paginator = ClerkPaginator(limit=100)
        assert paginator._limit == 100
        assert paginator._offset == 0
        assert paginator.has_next_page is True

    @pytest.mark.parametrize(
        ("label", "response_body", "has_next", "expected_offset"),
        [
            ("direct_array_full_page", [{"id": f"u{i}"} for i in range(100)], True, 100),
            ("direct_array_partial_page", [{"id": "u1"}, {"id": "u2"}], False, 0),
            ("wrapped_full_page", {"data": [{"id": f"o{i}"} for i in range(100)], "total_count": 250}, True, 100),
            # total_count exactly divisible by limit: skip the extra empty request.
            (
                "wrapped_full_terminal_page",
                {"data": [{"id": f"o{i}"} for i in range(100)], "total_count": 100},
                False,
                0,
            ),
            ("wrapped_partial_page", {"data": [{"id": "o1"}], "total_count": 1}, False, 0),
            ("empty_body", None, False, 0),
            ("empty_dict", {}, False, 0),
        ],
    )
    def test_update_state(self, label: str, response_body: Any, has_next: bool, expected_offset: int) -> None:
        paginator = ClerkPaginator(limit=100)
        response = MagicMock()
        response.json.return_value = response_body
        paginator.update_state(response)
        assert paginator._has_next_page is has_next
        assert paginator._offset == expected_offset

    @pytest.mark.parametrize(
        ("label", "seeded_offset", "expected_offset_param"),
        [
            ("fresh_run_omits_offset", None, None),
            ("resumed_sets_offset", 500, 500),
        ],
    )
    def test_init_request(self, label: str, seeded_offset: int | None, expected_offset_param: int | None) -> None:
        paginator = ClerkPaginator(limit=100)
        if seeded_offset is not None:
            paginator.set_resume_state({"offset": seeded_offset})

        request = Request(method="GET", url="https://api.clerk.com/v1/users", params={"limit": 100})
        paginator.init_request(request)

        if expected_offset_param is None:
            assert "offset" not in (request.params or {})
        else:
            assert request.params["offset"] == expected_offset_param

    def test_update_request_sets_offset_when_next_page(self) -> None:
        paginator = ClerkPaginator(limit=100)
        response = MagicMock()
        response.json.return_value = [{"id": f"u{i}"} for i in range(100)]
        paginator.update_state(response)

        request = Request(method="GET", url="https://api.clerk.com/v1/users", params={"limit": 100})
        paginator.update_request(request)

        assert request.params["offset"] == 100

    def test_get_resume_state_returns_current_offset(self) -> None:
        paginator = ClerkPaginator(limit=100)
        response = MagicMock()
        response.json.return_value = [{"id": f"u{i}"} for i in range(100)]
        paginator.update_state(response)  # _offset advances to 100
        assert paginator.get_resume_state() == {"offset": 100}

    def test_set_resume_state_round_trip(self) -> None:
        paginator = ClerkPaginator(limit=100)
        paginator.set_resume_state({"offset": 500})
        assert paginator._offset == 500
        assert paginator.has_next_page is True
        assert paginator.get_resume_state() == {"offset": 500}

    def test_set_resume_state_ignores_missing_offset(self) -> None:
        paginator = ClerkPaginator(limit=100)
        paginator.set_resume_state({})
        assert paginator._offset == 0


def _make_http_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


# ``users``/``invitations`` return direct arrays; ``organizations``/``organization_memberships``
# return ``{data: [...], total_count: N}`` wrapped responses. Both flavours share the same
# paginator semantics; the only behavioural difference is how rest_source extracts rows.
_DIRECT_ARRAY_ENDPOINT = "users"
_WRAPPED_ENDPOINT = "organizations"


def _full_page(endpoint: str, prefix: str) -> Any:
    items = [{"id": f"{prefix}{i}"} for i in range(100)]
    if endpoint == _WRAPPED_ENDPOINT:
        return {"data": items, "total_count": 9999}
    return items


def _partial_page(endpoint: str, ids: list[str]) -> Any:
    items = [{"id": i} for i in ids]
    if endpoint == _WRAPPED_ENDPOINT:
        return {"data": items, "total_count": len(items)}
    return items


class TestClerkSourceResumeBehavior:
    """End-to-end resume behaviour through the shared ``rest_api_resource`` path."""

    def _drive(self, endpoint: str, manager: MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
        """Drive ``clerk_source`` with a mocked HTTP session and return the
        params dict sent with each request (shallow copies — the paginator
        mutates the underlying Request in-place between pages)."""
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params))
            return next(response_iter)

        with patch(
            "posthog.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            source_response = clerk_source(
                secret_key="sk_live_test",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )
            list(cast(Iterable[Any], source_response.items()))
            return sent_params

    @pytest.mark.parametrize("endpoint", [_DIRECT_ARRAY_ENDPOINT, _WRAPPED_ENDPOINT])
    def test_fresh_run_saves_offset_after_each_non_terminal_page(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_full_page(endpoint, "a")),
            _make_http_response(_full_page(endpoint, "b")),
            _make_http_response(_partial_page(endpoint, ["c1", "c2"])),
        ]
        sent_params = self._drive(endpoint, manager, responses)

        # First request omits offset (fresh run); subsequent requests include it.
        assert [p.get("offset") for p in sent_params] == [None, 100, 200]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            ClerkResumeConfig(offset=100),
            ClerkResumeConfig(offset=200),
        ]

    @pytest.mark.parametrize("endpoint", [_DIRECT_ARRAY_ENDPOINT, _WRAPPED_ENDPOINT])
    def test_resume_seeds_paginator_with_saved_offset(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = ClerkResumeConfig(offset=200)

        responses = [
            _make_http_response(_partial_page(endpoint, ["c1", "c2"])),
        ]
        sent_params = self._drive(endpoint, manager, responses)

        # The very first request goes out at the resumed offset — no initial
        # offset-less call to re-fetch the already-synced pages.
        assert [p.get("offset") for p in sent_params] == [200]

    @pytest.mark.parametrize("endpoint", [_DIRECT_ARRAY_ENDPOINT, _WRAPPED_ENDPOINT])
    def test_terminal_single_page_does_not_save_state(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response(_partial_page(endpoint, ["only"])),
        ]
        self._drive(endpoint, manager, responses)

        manager.save_state.assert_not_called()

    @pytest.mark.parametrize("endpoint", [_DIRECT_ARRAY_ENDPOINT, _WRAPPED_ENDPOINT])
    def test_saved_state_with_zero_offset_is_ignored(self, endpoint: str) -> None:
        # A zero-offset checkpoint is equivalent to a fresh run — don't seed.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = ClerkResumeConfig(offset=0)

        responses = [
            _make_http_response(_partial_page(endpoint, ["u1"])),
        ]
        sent_params = self._drive(endpoint, manager, responses)

        assert [p.get("offset") for p in sent_params] == [None]

    def test_resume_config_serialization_round_trip(self) -> None:
        cfg = ClerkResumeConfig(offset=1500)
        as_json = json.dumps(dataclasses.asdict(cfg))
        reconstituted = ClerkResumeConfig(**json.loads(as_json))
        assert reconstituted == cfg
