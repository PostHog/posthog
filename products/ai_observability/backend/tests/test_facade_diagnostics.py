from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.paging import PageRequest

from products.ai_observability.backend.facade import api, diagnostics
from products.ai_observability.backend.facade.diagnostics_contracts import (
    ErrorFirstSeen,
    ErrorFirstSeenList,
    ErrorListCounts,
    ErrorNewCount,
    ErrorTrend,
    ToolFailureState,
    ToolListCounts,
)
from products.ai_observability.backend.logic.diagnostics.entity_keys import encode_entity_key
from products.ai_observability.backend.logic.traces.lookback import LOOKBACK
from products.ai_observability.backend.logic.traces.trace_selection import TraceSelection, TraceWindow

from .logic.diagnostics.test_error_group_queries import DAY, PERSON_A, _flagged
from .logic.diagnostics.test_tool_group_queries import _generation, _repeated
from .logic.traces.test_trace_selection_queries import at, seed, to_selection

TIMED_OUT = "Request timed out after <n> ms"
SCHEMA_REJECTED = "Tool schema rejected by provider"
REFUSED = "Upstream refused the request"
FETCH_PAGE = "fetch_page"
LOOKUP = "lookup"


def _bucket(hour: int) -> datetime:
    # The team's zone is UTC+05:30, so its hours start at half past in UTC.
    return datetime(2026, 9, 1, 9, 30, tzinfo=UTC) + timedelta(hours=hour)


class TestErrorsFacade(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.timezone = "Asia/Kolkata"
        self.team.save()
        # A UTC window, so the facade must move it to the project's zone to start buckets at local hours.
        self.selection = TraceSelection(window=TraceWindow(start=at(0), end=at(120)))

    def _seed_rising_and_new(self) -> None:
        seed(
            self.team,
            [
                *(
                    _flagged(TIMED_OUT, minute, f"timeout-{index}", person_id=PERSON_A)
                    for index, minute in enumerate(range(15, 111, 8))
                ),
                *(
                    _flagged(TIMED_OUT, minute, f"timeout-before-{index}", person_id=PERSON_A)
                    for index, minute in enumerate((-100, -90, -80, -70, -20))
                ),
                *(
                    _flagged(
                        SCHEMA_REJECTED,
                        minute,
                        f"schema-{minute}",
                        person_id=PERSON_A,
                        properties={"$ai_model": "gpt-4.1-mini"},
                    )
                    for minute in (10, 70)
                ),
            ],
        )

    def _list(self, *, offset: int = 0, order: diagnostics.ErrorOrder | None = None) -> diagnostics.ErrorPage:
        return diagnostics.load_error_list(
            self.team,
            self.user,
            self.selection,
            search=None,
            view=None,
            order=order,
            page=PageRequest(limit=50, offset=offset),
        )()

    @parameterized.expand(
        [
            ("asked_for_none", None, diagnostics.ErrorOrder.OCCURRENCES, [TIMED_OUT, SCHEMA_REJECTED]),
            (
                "asked_for_change",
                diagnostics.ErrorOrder.CHANGE,
                diagnostics.ErrorOrder.CHANGE,
                [SCHEMA_REJECTED, TIMED_OUT],
            ),
        ]
    )
    def test_list_reports_the_order_it_applied(
        self, _name: str, order: diagnostics.ErrorOrder | None, applied: diagnostics.ErrorOrder, messages: list[str]
    ) -> None:
        self._seed_rising_and_new()

        page = self._list(order=order)

        assert (page.order, [item.message for item in page.page.results]) == (applied, messages)

    def test_list_builds_a_page_of_error_groups_with_counts_and_buckets_in_the_project_zone(self) -> None:
        self._seed_rising_and_new()

        page = self._list()

        assert page.page.count == 2
        assert [item.message for item in page.page.results] == [TIMED_OUT, SCHEMA_REJECTED]
        rising, new = page.page.results
        assert (rising.change_label, rising.change_tone, rising.trend) == ("+140%", "bad", ErrorTrend.INCREASING)
        assert new.model_dump(by_alias=True) == {
            "key": encode_entity_key(SCHEMA_REJECTED),
            "message": SCHEMA_REJECTED,
            "occurrences": 2,
            "changeLabel": "was 0",
            "changeTone": "neutral",
            "trend": "steady",
            "traces": 2,
            "users": 1,
            "models": ["gpt-4.1-mini"],
            "lastSeen": at(70),
            "series": [1, 1, 0],
        }
        assert page.counts == ErrorListCounts(total=2, increasing=1, decreasing=0, max_occurrences=12)
        assert page.bucket_starts == [_bucket(0), _bucket(1), _bucket(2)]
        assert page.nothing_captured is False

    @parameterized.expand([("first_page", 0, True), ("later_page", 50, False)])
    def test_nothing_captured_when_the_only_error_is_past_the_lookback(
        self, _name: str, offset: int, expected: bool
    ) -> None:
        seed(self.team, [_flagged(REFUSED, -40 * DAY, "refused")])

        page = self._list(offset=offset)

        assert (page.page.count, page.nothing_captured) == (0, expected)

    def test_get_error_builds_the_list_item_with_both_periods_series(self) -> None:
        self._seed_rising_and_new()

        detail = diagnostics.get_error(self.team, self.user, self.selection, encode_entity_key(TIMED_OUT))()

        assert detail.item == self._list().page.results[0]
        assert detail.item.series == [2, 8, 2]
        assert detail.bucket_starts == [_bucket(0), _bucket(1), _bucket(2)]
        assert detail.previous_series == [1, 3, 1]

    def test_get_error_pairs_the_previous_series_with_the_range_buckets(self) -> None:
        # From 06:00 for two and a half days in the project's zone, so the previous period starts at 18:00 and spans one
        # more day than the range.
        start = 870
        seed(
            self.team,
            [
                _flagged(TIMED_OUT, start + 30, "in-range"),
                _flagged(TIMED_OUT, start - 50 * 60, "previous-second-day"),
                _flagged(TIMED_OUT, start - 60, "previous-extra-day"),
            ],
        )
        selection = TraceSelection(window=TraceWindow(start=at(start), end=at(start + 3600)))

        detail = diagnostics.get_error(self.team, self.user, selection, encode_entity_key(TIMED_OUT))()

        assert (len(detail.bucket_starts), detail.previous_series) == (3, [0, 1, 0])

    def test_an_errors_traces_is_the_total_of_the_traces_list_scoped_to_it(self) -> None:
        gpt_a, gpt_b = {"$ai_model": "gpt-a"}, {"$ai_model": "gpt-b"}
        seed(
            self.team,
            [
                _flagged(TIMED_OUT, 10, "matching", properties=gpt_a),
                _flagged(TIMED_OUT, 20, "matching", properties=gpt_a),
                _flagged(TIMED_OUT, 30, "matching-elsewhere", properties=gpt_b),
                {"event": "$ai_span", "trace_id": "matching-elsewhere", "minutes": 31, "properties": gpt_a},
                _flagged(TIMED_OUT, 40, "filtered-out", properties=gpt_b),
            ],
        )
        selection = to_selection(
            self.team,
            {
                "date_from": 0,
                "date_to": 120,
                "properties": [{"key": "$ai_model", "value": "gpt-a", "operator": "exact", "type": "event"}],
            },
        )

        [row] = diagnostics.load_error_list(
            self.team,
            self.user,
            selection,
            search=None,
            view=None,
            order=diagnostics.ErrorOrder.OCCURRENCES,
            page=PageRequest(limit=50),
        )().page.results
        scoped = api.load_trace_list(
            self.team, self.user, replace(selection, error=row.message), cursor=None, limit=50
        )()

        assert scoped.counts is not None
        assert row.traces == scoped.counts.total == 2

    @parameterized.expand(
        [
            ("never_raised", encode_entity_key("Never raised"), diagnostics.ErrorNotFoundError),
            ("malformed", "not a key!", diagnostics.MalformedEntityKeyError),
        ]
    )
    def test_get_error_refuses_a_key_with_no_group(self, _name: str, key: str, error: type[Exception]) -> None:
        self._seed_rising_and_new()

        with pytest.raises(error):
            diagnostics.get_error(self.team, self.user, self.selection, key)

    def test_new_count_counts_the_errors_first_seen_in_the_range(self) -> None:
        self._seed_rising_and_new()

        assert diagnostics.count_new_errors(self.team, self.user, self.selection, search=None) == ErrorNewCount(count=1)

    def test_first_seen_has_one_item_per_key_in_request_order_with_the_checked_date_and_newness(self) -> None:
        stale = "Stale cache entry"
        seed(
            self.team,
            [
                _flagged(stale, -int(LOOKBACK / timedelta(minutes=1)), "stale-before"),
                _flagged(stale, 5, "stale-now"),
                _flagged(SCHEMA_REJECTED, -5 * DAY, "schema-before"),
                _flagged(SCHEMA_REJECTED, 6, "schema-now"),
                _flagged(REFUSED, 0, "refused-now"),
            ],
        )
        keys = [encode_entity_key(message) for message in (stale, SCHEMA_REJECTED, REFUSED, "Never raised")]

        first_seen = diagnostics.load_error_first_seen(self.team, self.user, self.selection, [*keys, keys[0]])

        assert first_seen == ErrorFirstSeenList(
            items=[
                ErrorFirstSeen(key=keys[0], first_seen=at(0) - LOOKBACK, is_new=False),
                ErrorFirstSeen(key=keys[1], first_seen=at(-5 * DAY), is_new=False),
                ErrorFirstSeen(key=keys[2], first_seen=at(0), is_new=True),
                ErrorFirstSeen(key=keys[3], first_seen=None, is_new=False),
            ],
            checked_from=(at(0) - LOOKBACK).astimezone(self.team.timezone_info).date(),
        )

    def test_first_seen_refuses_more_keys_than_the_limit(self) -> None:
        keys = [encode_entity_key(f"Error {index}") for index in range(diagnostics.ERROR_FIRST_SEEN_MAX_KEYS + 1)]

        with pytest.raises(diagnostics.ErrorFirstSeenTooManyKeysError):
            diagnostics.load_error_first_seen(self.team, self.user, self.selection, keys)


class TestToolsFacade(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.timezone = "Asia/Kolkata"
        self.team.save()
        self.selection = TraceSelection(window=TraceWindow(start=at(0), end=at(120)))

    def _seed_captured_and_not_captured(self) -> None:
        seed(
            self.team,
            [
                _generation(10, "fetch-0", called=FETCH_PAGE),
                _generation(11, "fetch-0", results=_repeated(FETCH_PAGE, 20), errors=FETCH_PAGE),
                _generation(20, "fetch-1", called=FETCH_PAGE),
                _generation(30, "fetch-2", called=f"{FETCH_PAGE},{LOOKUP}"),
                _generation(-100, "fetch-before", called=FETCH_PAGE),
                _generation(-90, "fetch-before", called=FETCH_PAGE),
                _generation(80, "lookup-0", called=LOOKUP),
                _generation(50, "no-tools-0"),
            ],
        )

    def _list(self, *, offset: int = 0, order: diagnostics.ToolOrder | None = None) -> diagnostics.ToolPage:
        return diagnostics.load_tool_list(
            self.team,
            self.user,
            self.selection,
            search=None,
            view=None,
            order=order,
            page=PageRequest(limit=50, offset=offset),
        )()

    @parameterized.expand(
        [
            ("asked_for_none", None, diagnostics.ToolOrder.CALLS, [FETCH_PAGE, LOOKUP]),
            ("asked_for_change", diagnostics.ToolOrder.CHANGE, diagnostics.ToolOrder.CHANGE, [LOOKUP, FETCH_PAGE]),
        ]
    )
    def test_list_reports_the_order_it_applied(
        self, _name: str, order: diagnostics.ToolOrder | None, applied: diagnostics.ToolOrder, names: list[str]
    ) -> None:
        self._seed_captured_and_not_captured()

        page = self._list(order=order)

        assert (page.order, [item.name for item in page.page.results]) == (applied, names)

    def test_list_builds_a_page_of_tools_with_failure_states(self) -> None:
        self._seed_captured_and_not_captured()

        page = self._list()

        assert page.page.count == 2
        captured, not_captured = page.page.results
        assert (
            captured.name,
            captured.change_label,
            captured.failure_rate,
            captured.failures,
            captured.failure_state,
            captured.is_failing,
            captured.only_tool_share,
        ) == (FETCH_PAGE, "+50%", 0.05, 1, ToolFailureState.CAPTURED, True, 2 / 3)
        assert not_captured.model_dump(by_alias=True) == {
            "key": encode_entity_key(LOOKUP),
            "name": LOOKUP,
            "calls": 2,
            "changeLabel": "was 0",
            "changeTone": "neutral",
            "traces": 2,
            "failureRate": None,
            "failures": None,
            "failureState": "not_captured",
            "isFailing": False,
            "onlyToolShare": 0.5,
            "lastSeen": at(80),
            "series": [0, 2, 0],
        }
        assert page.counts == ToolListCounts(total=2, failing=1, max_calls=3)
        assert page.bucket_starts == [_bucket(0), _bucket(1), _bucket(2)]
        assert page.nothing_captured is False

    def test_a_tools_traces_is_the_total_of_the_traces_list_scoped_to_it(self) -> None:
        def call(minute: int, trace_id: str, model: str) -> dict[str, Any]:
            event = _generation(minute, trace_id, called=FETCH_PAGE)
            return {**event, "properties": {**event["properties"], "$ai_model": model}}

        seed(
            self.team,
            [
                call(10, "matching", "gpt-a"),
                call(20, "matching", "gpt-a"),
                call(30, "matching-elsewhere", "gpt-b"),
                {
                    "event": "$ai_span",
                    "trace_id": "matching-elsewhere",
                    "minutes": 31,
                    "properties": {"$ai_model": "gpt-a"},
                },
                call(40, "filtered-out", "gpt-b"),
            ],
        )
        selection = to_selection(
            self.team,
            {
                "date_from": 0,
                "date_to": 120,
                "properties": [{"key": "$ai_model", "value": "gpt-a", "operator": "exact", "type": "event"}],
            },
        )

        [row] = diagnostics.load_tool_list(
            self.team,
            self.user,
            selection,
            search=None,
            view=None,
            order=diagnostics.ToolOrder.CALLS,
            page=PageRequest(limit=50),
        )().page.results
        scoped = api.load_trace_list(self.team, self.user, replace(selection, tool=row.name), cursor=None, limit=50)()

        assert scoped.counts is not None
        assert row.traces == scoped.counts.total == 2

    @parameterized.expand([("called_in_the_lookback", -5 * DAY, False), ("called_past_the_lookback", -40 * DAY, True)])
    def test_nothing_captured_only_when_no_tool_was_called_since_the_lookback_start(
        self, _name: str, minute: int, expected: bool
    ) -> None:
        seed(self.team, [_generation(minute, "lookup-before", called=LOOKUP)])

        page = self._list()

        assert (page.page.count, page.nothing_captured) == (0, expected)

    def test_get_tool_builds_the_list_item_with_both_periods_series(self) -> None:
        self._seed_captured_and_not_captured()

        detail = diagnostics.get_tool(self.team, self.user, self.selection, encode_entity_key(FETCH_PAGE))()

        assert detail.item == self._list().page.results[0]
        assert detail.item.series == [2, 1, 0]
        assert detail.bucket_starts == [_bucket(0), _bucket(1), _bucket(2)]
        assert detail.previous_series == [1, 1, 0]

    @parameterized.expand(
        [
            ("never_called", encode_entity_key("never_called"), diagnostics.ToolNotFoundError),
            ("malformed", "not a key!", diagnostics.MalformedEntityKeyError),
        ]
    )
    def test_get_tool_refuses_a_key_with_no_tool(self, _name: str, key: str, error: type[Exception]) -> None:
        self._seed_captured_and_not_captured()

        with pytest.raises(error):
            diagnostics.get_tool(self.team, self.user, self.selection, key)


_LOADERS: list[tuple[str, Callable[..., Any]]] = [
    (
        "list",
        lambda team, user, selection: diagnostics.load_error_list(
            team,
            user,
            selection,
            search=None,
            view=None,
            order=diagnostics.ErrorOrder.OCCURRENCES,
            page=PageRequest(limit=50),
        ),
    ),
    ("detail", lambda team, user, selection: diagnostics.get_error(team, user, selection, encode_entity_key("E"))),
    ("new_count", lambda team, user, selection: diagnostics.count_new_errors(team, user, selection, search=None)),
    (
        "first_seen",
        lambda team, user, selection: diagnostics.load_error_first_seen(
            team, user, selection, [encode_entity_key("E")]
        ),
    ),
    (
        "tool_list",
        lambda team, user, selection: diagnostics.load_tool_list(
            team,
            user,
            selection,
            search=None,
            view=None,
            order=diagnostics.ToolOrder.CALLS,
            page=PageRequest(limit=50),
        ),
    ),
    ("tool_detail", lambda team, user, selection: diagnostics.get_tool(team, user, selection, encode_entity_key("T"))),
]
_REFUSED_WINDOWS: list[tuple[str, TraceWindow, type[Exception]]] = [
    (
        "too_many_buckets",
        TraceWindow(start=datetime(1900, 1, 1, tzinfo=UTC), end=datetime(2026, 9, 1, tzinfo=UTC)),
        diagnostics.DiagnosticsRangeTooLongError,
    ),
    (
        "lookback_before_the_first_date",
        TraceWindow(start=datetime(1, 1, 20, tzinfo=UTC), end=datetime(1, 1, 21, tzinfo=UTC)),
        diagnostics.InvalidTraceWindowError,
    ),
]


class TestDiagnosticsFacadeRefusals(BaseTest):
    @parameterized.expand(
        [
            (f"{loader_name}_{window_name}", load, window, error)
            for loader_name, load in _LOADERS
            for window_name, window, error in _REFUSED_WINDOWS
        ]
    )
    def test_refuses_a_window_it_cannot_read_before_reading(
        self, _name: str, load: Callable[..., Any], window: TraceWindow, error: type[Exception]
    ) -> None:
        with pytest.raises(error):
            load(self.team, self.user, TraceSelection(window=window))
