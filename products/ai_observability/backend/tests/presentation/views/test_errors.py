import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.hogql.errors import ExposedHogQLError

from posthog.paging import Page, PageRequest

from products.ai_observability.backend.facade import api, diagnostics
from products.ai_observability.backend.facade.contracts import TraceMetricChangeTone, TraceMetricsRangeTooLong
from products.ai_observability.backend.facade.diagnostics_contracts import (
    ErrorFirstSeen,
    ErrorFirstSeenList,
    ErrorGroupDetail,
    ErrorList,
    ErrorListCounts,
    ErrorListItem,
    ErrorNewCount,
    ErrorPage,
    ErrorTrend,
)
from products.ai_observability.backend.presentation.views import diagnostics_resource

from ...logic.diagnostics.test_error_group_queries import _flagged
from ...logic.traces.test_trace_selection_queries import T0, seed
from .trace_fixtures import QuerySlotRecorder

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

KEY = "VGltZWQgb3V0"
STARTS = [datetime(2026, 9, 1, 9, tzinfo=UTC), datetime(2026, 9, 1, 10, tzinfo=UTC)]
CUSTOM_EXPRESSION = json.dumps([{"type": "hogql", "key": "properties.$ai_model = 'gpt-test'"}])

ITEM = ErrorListItem(
    key=KEY,
    message="Timed out",
    occurrences=12,
    change_label="+50%",
    change_tone=TraceMetricChangeTone.BAD,
    trend=ErrorTrend.INCREASING,
    traces=9,
    users=4,
    models=["gpt-4.1-mini"],
    last_seen=datetime(2026, 9, 1, 10, 42, tzinfo=UTC),
    series=[5, 7],
)
COUNTS = ErrorListCounts(total=3, increasing=1, decreasing=0, max_occurrences=7)


def _error_page(_team: object, _user: object, _selection: object, **_kwargs: object) -> Callable[[], ErrorPage]:
    return lambda: ErrorPage(
        page=Page(results=[ITEM], count=3),
        counts=COUNTS,
        bucket_starts=STARTS,
        nothing_captured=False,
        order=diagnostics.ErrorOrder.TRACES,
    )


def _error_detail(*_args: object) -> Callable[[], ErrorGroupDetail]:
    return lambda: ErrorGroupDetail(item=ITEM, bucket_starts=STARTS, previous_series=[1, 2])


def _first_seen(*_args: object) -> ErrorFirstSeenList:
    return ErrorFirstSeenList(
        items=[ErrorFirstSeen(key=KEY, first_seen=STARTS[0], is_new=True)], checked_from=STARTS[0].date()
    )


def _new_count(*_args: object, **_kwargs: object) -> ErrorNewCount:
    return ErrorNewCount(count=4)


class TestErrorViews(APIBaseTest):
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
        base = f"/api/projects/{self.team.id}/ai_observability/errors/"
        if endpoint == "list":
            return self.client.get(base, params or {}, headers=headers)
        if endpoint == "retrieve":
            return self.client.get(f"{base}{KEY}/", params or {}, headers=headers)
        if endpoint == "new_count":
            return self.client.get(f"{base}new_count/", params or {}, headers=headers)
        return self.client.post(
            f"{base}first_seen/?{urlencode(params or {})}",
            {"keys": [KEY] if keys is None else keys},
            format="json",
            headers=headers,
        )

    @contextmanager
    def _facade(self) -> Iterator[dict[str, MagicMock]]:
        with (
            patch.object(diagnostics, "load_error_list", side_effect=_error_page) as load_list,
            patch.object(diagnostics, "get_error", side_effect=_error_detail) as get_error,
            patch.object(diagnostics, "load_error_first_seen", side_effect=_first_seen) as first_seen,
            patch.object(diagnostics, "count_new_errors", side_effect=_new_count) as new_count,
        ):
            yield {"list": load_list, "retrieve": get_error, "first_seen": first_seen, "new_count": new_count}

    def test_list_hands_its_params_to_the_facade_and_pages_its_answer(self) -> None:
        with self._facade() as facade:
            response = self._request(
                "list",
                {
                    "date_from": "2026-09-01T00:00:00Z",
                    "date_to": "2026-09-02T00:00:00Z",
                    "filter_test_accounts": "true",
                    "group_key": "acme",
                    "group_type_index": 1,
                    "search": "timed out",
                    "view": "increasing",
                    "order": "change",
                    "limit": 1,
                    "offset": 1,
                },
            )

        assert response.status_code == 200, response.json()
        selection = facade["list"].call_args.args[2]
        assert (selection.window.start, selection.window.end) == (
            datetime(2026, 9, 1, tzinfo=UTC),
            datetime(2026, 9, 2, tzinfo=UTC),
        )
        assert (selection.filter_test_accounts, selection.group, selection.search) == (
            True,
            api.TraceGroupScope(key="acme", type_index=1),
            None,
        )
        assert facade["list"].call_args.kwargs == {
            "search": "timed out",
            "view": "increasing",
            "order": "change",
            "page": PageRequest(limit=1, offset=1),
        }
        body = response.json()
        assert "offset=2" in body["next"] and "offset" not in body["previous"]
        assert {name: value for name, value in body.items() if name not in ("next", "previous")} == {
            "count": 3,
            "results": [ITEM.model_dump(mode="json", by_alias=True)],
            "counts": {"total": 3, "increasing": 1, "decreasing": 0, "maxOccurrences": 7},
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

    def test_retrieve_takes_the_list_filters(self) -> None:
        with self._facade() as facade:
            response = self._request(
                "retrieve", {"date_from": "2026-09-01T00:00:00Z", "group_key": "acme", "group_type_index": 1}
            )

        assert response.status_code == 200, response.json()
        team, _user, selection, key = facade["retrieve"].call_args.args
        assert (team, selection.window.start, selection.group, key) == (
            self.team,
            datetime(2026, 9, 1, tzinfo=UTC),
            api.TraceGroupScope(key="acme", type_index=1),
            KEY,
        )

    def test_new_count_takes_the_list_filters_and_search(self) -> None:
        with self._facade() as facade:
            response = self._request(
                "new_count",
                {
                    "date_from": "2026-09-01T00:00:00Z",
                    "filter_test_accounts": "true",
                    "group_key": "acme",
                    "group_type_index": 1,
                    "search": "timed out",
                },
            )

        assert (response.status_code, response.json()) == (200, {"count": 4})
        team, _user, selection = facade["new_count"].call_args.args
        assert (team, selection.window.start, selection.filter_test_accounts, selection.group) == (
            self.team,
            datetime(2026, 9, 1, tzinfo=UTC),
            True,
            api.TraceGroupScope(key="acme", type_index=1),
        )
        assert facade["new_count"].call_args.kwargs == {"search": "timed out"}

    def test_first_seen_takes_only_the_range_and_the_test_account_switch(self) -> None:
        with self._facade() as facade:
            response = self._request(
                "first_seen",
                {
                    "date_from": "2026-09-01T00:00:00Z",
                    "filter_test_accounts": "true",
                    "properties": CUSTOM_EXPRESSION,
                    "group_key": "acme",
                    "group_type_index": 1,
                },
            )

        assert response.status_code == 200, response.json()
        _team, _user, selection, keys = facade["first_seen"].call_args.args
        assert (selection.window.start, selection.filter_test_accounts, selection.properties, selection.group) == (
            datetime(2026, 9, 1, tzinfo=UTC),
            True,
            (),
            None,
        )
        assert keys == [KEY]

    @parameterized.expand(
        [
            ("limit too large", "list", {"limit": 101}),
            ("limit too small", "list", {"limit": 0}),
            ("negative offset", "list", {"offset": -1}),
            ("unknown view", "list", {"view": "errors"}),
            ("unknown order", "list", {"order": "newest"}),
            ("unparsable filters", "list", {"properties": "{"}),
            ("group key alone", "retrieve", {"group_key": "acme"}),
            ("unparsable date", "first_seen", {"date_from": "last tuesday"}),
        ]
    )
    def test_bad_input_is_a_400(self, _name: str, endpoint: str, params: dict[str, Any]) -> None:
        with self._facade():
            assert self._request(endpoint, params).status_code == 400

    @parameterized.expand([("none", []), ("over the cap", [KEY] * 101)])
    def test_first_seen_takes_one_to_a_hundred_keys(self, _name: str, keys: list[str]) -> None:
        with self._facade():
            assert self._request("first_seen", keys=keys).status_code == 400

    @parameterized.expand(
        [
            ("too long a range", "list", diagnostics.DiagnosticsRangeTooLongError(), 422),
            ("too long a range", "retrieve", diagnostics.DiagnosticsRangeTooLongError(), 422),
            ("too long a range", "first_seen", diagnostics.DiagnosticsRangeTooLongError(), 422),
            ("too long a range", "new_count", diagnostics.DiagnosticsRangeTooLongError(), 422),
            ("unreadable window", "list", diagnostics.InvalidTraceWindowError("Out of range"), 400),
            ("rejected filter", "list", api.InvalidTraceSelectionError("Remove them."), 400),
            ("hogql error", "list", ExposedHogQLError("Bad expression"), 400),
            ("malformed key", "retrieve", diagnostics.MalformedEntityKeyError(KEY), 400),
            ("unknown key", "retrieve", diagnostics.ErrorNotFoundError(KEY), 404),
            ("malformed key", "first_seen", diagnostics.MalformedEntityKeyError(KEY), 400),
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

    @parameterized.expand([("list",), ("retrieve",), ("first_seen",), ("new_count",)])
    def test_a_read_key_reaches_every_endpoint(self, endpoint: str) -> None:
        with self._facade():
            assert self._request(endpoint, scopes=["llm_analytics:read"]).status_code == 200
            assert self._request(endpoint, scopes=["query:read"]).status_code == 403

    @parameterized.expand([("list",), ("retrieve",), ("new_count",)])
    def test_a_custom_expression_needs_the_query_scope(self, endpoint: str) -> None:
        with self._facade():
            response = self._request(endpoint, {"properties": CUSTOM_EXPRESSION}, scopes=["llm_analytics:read"])

        assert response.status_code == 403
        assert "query:read" in response.json()["detail"]


@time_machine.travel(T0 + timedelta(hours=2), tick=False)
class TestErrorListReads(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        seed(self.team, [_flagged("Request timed out after <n> ms", minute, f"trace-{minute}") for minute in (5, 40)])

    def _list(self) -> "_MonkeyPatchedResponse":
        return self.client.get(f"/api/projects/{self.team.id}/ai_observability/errors/", {"date_from": "-3h"})

    def test_a_page_matches_its_contract(self) -> None:
        response = self._list()

        assert response.status_code == 200, response.json()
        body = response.json()
        assert ErrorList.model_validate(body).model_dump(mode="json", by_alias=True) == body
        assert [item["occurrences"] for item in body["results"]] == [2]

    def test_a_page_is_built_after_its_query_slot_is_released(self) -> None:
        with QuerySlotRecorder().recording(
            "load_error_list", facade=diagnostics, resource=diagnostics_resource
        ) as recorder:
            response = self._list()

        assert (response.status_code, recorder.loaded_while_holding, recorder.built_while_holding) == (
            200,
            [True],
            [False],
        )
