from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.paging import Page, PageRequest

from products.ai_observability.backend.facade import api, diagnostics
from products.ai_observability.backend.facade.contracts import TraceMetricChangeTone, TraceMetricsRangeTooLong
from products.ai_observability.backend.facade.diagnostics_contracts import (
    ToolFailureState,
    ToolGroupDetail,
    ToolList,
    ToolListCounts,
    ToolListItem,
    ToolPage,
    ToolTraceShare,
    ToolTraceShareList,
)
from products.ai_observability.backend.presentation.views.list_filters import MAX_SCOPE_TEXT_LENGTH

from ...logic.diagnostics.test_tool_group_queries import _generation
from ...logic.traces.test_trace_selection_queries import T0, seed

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

KEY = "ZmV0Y2hfcGFnZQ"
LONGEST_KEY = "k" * MAX_SCOPE_TEXT_LENGTH
STARTS = [datetime(2026, 9, 1, 9, tzinfo=UTC), datetime(2026, 9, 1, 10, tzinfo=UTC)]

ITEM = ToolListItem(
    key=KEY,
    name="fetch_page",
    calls=12,
    change_label="+50%",
    change_tone=TraceMetricChangeTone.NEUTRAL,
    traces=9,
    failure_rate=0.25,
    failures=3,
    failure_state=ToolFailureState.CAPTURED,
    is_failing=True,
    only_tool_share=0.5,
    last_seen=datetime(2026, 9, 1, 10, 42, tzinfo=UTC),
    series=[5, 7],
)


def _tool_page(_team: object, _user: object, _selection: object, **_kwargs: object) -> Callable[[], ToolPage]:
    return lambda: ToolPage(
        page=Page(results=[ITEM], count=3),
        counts=ToolListCounts(total=3, failing=1, max_calls=12),
        bucket_starts=STARTS,
        nothing_captured=False,
        order=diagnostics.ToolOrder.TRACES,
    )


def _tool_detail(*_args: object) -> Callable[[], ToolGroupDetail]:
    return lambda: ToolGroupDetail(item=ITEM, bucket_starts=STARTS, previous_series=[1, 2])


def _trace_shares(*_args: object) -> ToolTraceShareList:
    return ToolTraceShareList(items=[ToolTraceShare(key=KEY, trace_share=0.45)])


class TestToolViews(APIBaseTest):
    def _request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        *,
        keys: list[str] | None = None,
        scopes: list[str] | None = None,
    ) -> "_MonkeyPatchedResponse":
        headers = {}
        if scopes is not None:
            self.client.logout()
            headers["authorization"] = f"Bearer {self.create_personal_api_key_with_scopes(scopes)}"
        base = f"/api/projects/{self.team.id}/ai_observability/tools/"
        if endpoint == "trace_shares":
            return self.client.post(
                f"{base}trace_shares/?{urlencode(params or {})}",
                {"keys": [KEY] if keys is None else keys},
                format="json",
                headers=headers,
            )
        return self.client.get(base if endpoint == "list" else f"{base}{KEY}/", params or {}, headers=headers)

    @contextmanager
    def _facade(self) -> Iterator[dict[str, MagicMock]]:
        with (
            patch.object(diagnostics, "load_tool_list", side_effect=_tool_page) as load_list,
            patch.object(diagnostics, "get_tool", side_effect=_tool_detail) as get_tool,
            patch.object(diagnostics, "load_tool_trace_shares", side_effect=_trace_shares) as trace_shares,
        ):
            yield {"list": load_list, "retrieve": get_tool, "trace_shares": trace_shares}

    def test_list_hands_its_params_to_the_facade_and_pages_its_answer(self) -> None:
        with self._facade() as facade:
            response = self._request(
                "list",
                {
                    "date_from": "2026-09-01T00:00:00Z",
                    "date_to": "2026-09-02T00:00:00Z",
                    "group_key": "acme",
                    "group_type_index": 1,
                    "search": "fetch",
                    "view": "failing",
                    "order": "failure_rate",
                    "limit": 1,
                    "offset": 1,
                },
            )

        assert response.status_code == 200, response.json()
        selection = facade["list"].call_args.args[2]
        assert (selection.window.start, selection.group, selection.search) == (
            datetime(2026, 9, 1, tzinfo=UTC),
            api.TraceGroupScope(key="acme", type_index=1),
            None,
        )
        assert facade["list"].call_args.kwargs == {
            "search": "fetch",
            "view": "failing",
            "order": "failure_rate",
            "page": PageRequest(limit=1, offset=1),
        }
        body = response.json()
        assert "offset=2" in body["next"] and "offset" not in body["previous"]
        assert {name: value for name, value in body.items() if name not in ("next", "previous")} == {
            "count": 3,
            "results": [ITEM.model_dump(mode="json", by_alias=True)],
            "counts": {"total": 3, "failing": 1, "maxCalls": 12},
            "bucketStarts": ["2026-09-01T09:00:00Z", "2026-09-01T10:00:00Z"],
            "nothingCaptured": False,
            "order": "traces",
        }

    def test_list_defaults_to_the_first_page_and_leaves_the_order_to_the_facade(self) -> None:
        with self._facade() as facade:
            response = self._request("list")

        assert (response.status_code, response.json()["order"]) == (200, "traces")
        assert facade["list"].call_args.kwargs == {
            "search": None,
            "view": None,
            "order": None,
            "page": PageRequest(limit=50, offset=0),
        }

    def test_retrieve_takes_the_list_filters_and_the_key(self) -> None:
        with self._facade() as facade:
            response = self._request(
                "retrieve", {"date_from": "2026-09-01T00:00:00Z", "group_key": "acme", "group_type_index": 1}
            )

        assert response.status_code == 200, response.json()
        assert response.json() == ToolGroupDetail(item=ITEM, bucket_starts=STARTS, previous_series=[1, 2]).model_dump(
            mode="json", by_alias=True
        )
        team, _user, selection, key = facade["retrieve"].call_args.args
        assert (team, selection.window.start, selection.group, key) == (
            self.team,
            datetime(2026, 9, 1, tzinfo=UTC),
            api.TraceGroupScope(key="acme", type_index=1),
            KEY,
        )

    def test_trace_shares_take_the_list_filters_and_the_keys(self) -> None:
        with self._facade() as facade:
            response = self._request(
                "trace_shares",
                {"date_from": "2026-09-01T00:00:00Z", "group_key": "acme", "group_type_index": 1},
                keys=[KEY, LONGEST_KEY],
            )

        assert (response.status_code, response.json()) == (200, {"items": [{"key": KEY, "traceShare": 0.45}]})
        team, _user, selection, keys = facade["trace_shares"].call_args.args
        assert (team, selection.window.start, selection.group, keys) == (
            self.team,
            datetime(2026, 9, 1, tzinfo=UTC),
            api.TraceGroupScope(key="acme", type_index=1),
            [KEY, LONGEST_KEY],
        )

    @parameterized.expand(
        [("none", []), ("over the cap", [KEY] * 101), ("a key too long", ["k" * (MAX_SCOPE_TEXT_LENGTH + 1)])]
    )
    def test_trace_shares_take_one_to_a_hundred_keys_of_bounded_length(self, _name: str, keys: list[str]) -> None:
        with self._facade():
            assert self._request("trace_shares", keys=keys).status_code == 400

    @parameterized.expand(
        [
            ("unknown view", "list", {"view": "increasing"}),
            ("unknown order", "list", {"order": "occurrences"}),
            ("limit too large", "list", {"limit": 101}),
            ("offset past the sorted tools", "list", {"offset": diagnostics.DIAGNOSTICS_PAGE_MAX_OFFSET + 1}),
            ("group key alone", "retrieve", {"group_key": "acme"}),
        ]
    )
    def test_bad_input_is_a_400(self, _name: str, endpoint: str, params: dict[str, Any]) -> None:
        with self._facade():
            assert self._request(endpoint, params).status_code == 400

    @parameterized.expand(
        [
            ("too long a range", "list", diagnostics.DiagnosticsRangeTooLongError(), 422),
            ("too long a range", "retrieve", diagnostics.DiagnosticsRangeTooLongError(), 422),
            ("unreadable window", "list", diagnostics.InvalidTraceWindowError("Out of range"), 400),
            ("malformed key", "retrieve", diagnostics.MalformedEntityKeyError(KEY), 400),
            ("unknown key", "retrieve", diagnostics.ToolNotFoundError(KEY), 404),
            ("too long a range", "trace_shares", diagnostics.DiagnosticsRangeTooLongError(), 422),
            ("malformed key", "trace_shares", diagnostics.MalformedEntityKeyError(KEY), 400),
        ]
    )
    def test_a_facade_error_maps_to_its_status(
        self, _name: str, endpoint: str, error: Exception, expected_status: int
    ) -> None:
        with self._facade() as facade:
            facade[endpoint].side_effect = error
            response = self._request(endpoint)

        assert response.status_code == expected_status
        if expected_status == 422:
            assert response.json() == TraceMetricsRangeTooLong().model_dump()

    @parameterized.expand([("list",), ("retrieve",), ("trace_shares",)])
    def test_a_read_key_reaches_every_endpoint(self, endpoint: str) -> None:
        with self._facade():
            assert self._request(endpoint, scopes=["llm_analytics:read"]).status_code == 200
            assert self._request(endpoint, scopes=["query:read"]).status_code == 403


@time_machine.travel(T0 + timedelta(hours=2), tick=False)
class TestToolListReads(ClickhouseTestMixin, APIBaseTest):
    def test_a_page_matches_its_contract(self) -> None:
        seed(self.team, [_generation(minute, f"trace-{minute}", called="fetch_page") for minute in (5, 40)])

        response = self.client.get(f"/api/projects/{self.team.id}/ai_observability/tools/", {"date_from": "-3h"})

        assert response.status_code == 200, response.json()
        body = response.json()
        assert ToolList.model_validate(body).model_dump(mode="json", by_alias=True) == body
        assert [item["calls"] for item in body["results"]] == [2]
