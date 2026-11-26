import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    create_person_id_override_by_distinct_id,
    patch_clickhouse_client_execute,
)

from parameterized import parameterized
from pydantic import TypeAdapter

from posthog.schema import AnyPropertyFilterDiscriminated

from posthog.models import Organization, Team
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.event.util import bulk_create_events
from posthog.models.group.util import create_group

from products.ai_observability.backend.logic.traces.trace_paging import (
    AroundTakes,
    around_takes,
    page_after,
    page_around,
    rows_to_read,
)
from products.ai_observability.backend.logic.traces.trace_selection import (
    CAPTURE_BUFFER,
    InvalidTraceSelectionError,
    TraceGroupScope,
    TracePosition,
    TraceSelection,
    TraceWindow,
)
from products.ai_observability.backend.logic.traces.trace_selection_queries import (
    SELECTION_QUERY_NAME,
    SelectionCounts,
    _reads_beyond_posthog_tables,
    load_rows_after,
    load_rows_around,
    load_rows_before,
)
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.event_definitions.backend.models.property_definition import PropertyDefinition

T0 = datetime(2026, 9, 1, 10, 0, 0, 123456, tzinfo=UTC)
CASES_PATH = Path(__file__).parents[4] / "shared" / "trace_selection_cases.json"
_PROPERTY_FILTER = TypeAdapter(AnyPropertyFilterDiscriminated)


def load_cases() -> list[dict[str, Any]]:
    """The trace selection's behaviour as cases. This read runs them, and the traces list runner will run them too
    once it reads through the selection.

    The file is a JSON list of cases. Every time is an offset from one base time the runner picks: whole minutes,
    plus optional microseconds.

    - `name`: what the case shows.
    - `team_test_account_filters` (optional): the team's test account filters, as property filter objects.
    - `team_test_account_filters_default_checked` (optional): whether the project filters test accounts by default.
    - `events`: each with `event`, `trace_id` (stored as `$ai_trace_id`), `minutes`, and optionally `microseconds`
      added to that offset, `properties`, `distinct_id` and `person_id`. Every event is written to both the shared
      events table and ai_events.
    - `selection`: `date_from` and `date_to` in minutes, and optionally `properties` (property filter objects),
      `filter_test_accounts`, `include_support_traces`, `search`, `quick_filter` (`errors` or `feedback`),
      `person_id`, `group` as `{"key", "type_index"}`, `order` (`newest_first` or `oldest_first`) and `session_id`.
    - `expected_trace_ids`: the first page, in the selection's order.
    - `expected_counts`: `total`, `errors` and `feedback` for the selection without its quick filter, or null for a
      session scope, which reads no counts.
    """
    return json.loads(CASES_PATH.read_text())


CASES = load_cases()


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def seed(team: Team, events: list[dict[str, Any]]) -> None:
    # An insert with no rows waits for data until the client times out.
    if not events:
        return
    rows = [
        {
            "event": event["event"],
            "event_uuid": f"00000000-0000-4000-8000-{index:012d}",
            "distinct_id": event.get("distinct_id", "distinct-1"),
            "team": team,
            "timestamp": at(event["minutes"]) + timedelta(microseconds=event.get("microseconds", 0)),
            "properties": {"$ai_trace_id": event["trace_id"], **event.get("properties", {})},
            **({"person_id": event["person_id"]} if "person_id" in event else {}),
        }
        for index, event in enumerate(events)
    ]
    bulk_create_events(rows)
    bulk_create_ai_events(rows)


def to_selection(team: Team, selection: dict[str, Any]) -> TraceSelection:
    group = selection.get("group")
    return TraceSelection(
        window=TraceWindow(
            start=at(selection["date_from"]).astimezone(team.timezone_info),
            end=at(selection["date_to"]).astimezone(team.timezone_info),
        ),
        properties=tuple(_PROPERTY_FILTER.validate_python(item) for item in selection.get("properties", [])),
        filter_test_accounts=selection.get("filter_test_accounts"),
        include_support_traces=selection.get("include_support_traces", False),
        search=selection.get("search"),
        person_id=selection.get("person_id"),
        group=TraceGroupScope(key=group["key"], type_index=group["type_index"]) if group else None,
        quick_filter=selection.get("quick_filter"),
        session_id=selection.get("session_id"),
        order=selection.get("order", "newest_first"),
    )


class TestTraceSelectionQueries(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Away from UTC, a bound or a position read as a wall-clock time instead of an instant lands in the wrong place.
        self.team.timezone = "Asia/Kolkata"
        self.team.save()

    def _selection(self, **overrides: Any) -> TraceSelection:
        return to_selection(self.team, {"date_from": -60, "date_to": 60, **overrides})

    @parameterized.expand([(case["name"], case) for case in CASES])
    def test_selection_case(self, _name: str, case: dict[str, Any]) -> None:
        if "team_test_account_filters" in case:
            self.team.test_account_filters = case["team_test_account_filters"]
        self.team.test_account_filters_default_checked = case.get("team_test_account_filters_default_checked", False)
        self.team.save()
        seed(self.team, case["events"])

        read = load_rows_after(self.team, self.user, to_selection(self.team, case["selection"]), after=None, take=50)

        assert [position.trace_id for position in read.rows.positions] == case["expected_trace_ids"]
        assert (asdict(read.counts) if read.counts else None) == case["expected_counts"]

    def _page_through(self, limit: int, selection: TraceSelection | None = None) -> list[TracePosition]:
        selection = selection or self._selection()
        seen: list[TracePosition] = []
        after: TracePosition | None = None
        # Bounded, so a cursor that keeps handing back earlier traces fails instead of paging forever.
        for _ in range(20):
            page = page_after(
                load_rows_after(self.team, self.user, selection, after=after, take=rows_to_read(limit)).rows, limit
            )
            seen += page.positions
            if page.next_after is None:
                return seen
            after = page.next_after
        raise AssertionError(f"Paging did not end after {seen}")

    def test_paging_through_equal_timestamps_neither_repeats_nor_skips(self) -> None:
        seed(self.team, [{"event": "$ai_generation", "trace_id": f"t{i:02d}", "minutes": 0} for i in range(7)])

        assert [position.trace_id for position in self._page_through(limit=3)] == [f"t{i:02d}" for i in range(7)]

    @parameterized.expand(
        [
            # T0 sits at .123456, so up to 543µs later is still the same millisecond.
            ("one millisecond pages by id", {"a": 100, "b": 200, "c": 300}, ["a", "b", "c"]),
            ("different milliseconds page newest first", {"a": 0, "b": 1000}, ["b", "a"]),
        ]
    )
    def test_paging_orders_by_the_millisecond_of_the_first_event(
        self, _name: str, first_event_microseconds: dict[str, int], expected_order: list[str]
    ) -> None:
        seed(
            self.team,
            [
                {"event": "$ai_generation", "trace_id": trace_id, "minutes": 0, "microseconds": microseconds}
                for trace_id, microseconds in first_event_microseconds.items()
            ],
        )

        assert self._page_through(limit=1) == [
            TracePosition(
                trace_id=trace_id, first_timestamp=T0 + timedelta(microseconds=first_event_microseconds[trace_id])
            )
            for trace_id in expected_order
        ]

    @parameterized.expand([("errors", ["failed-late", "failed-early"]), ("feedback", [])])
    def test_paging_a_quick_filter_returns_only_its_traces(self, quick_filter: str, expected: list[str]) -> None:
        seed(
            self.team,
            [
                {"event": "$ai_generation", "trace_id": "healthy-late", "minutes": 4},
                {
                    "event": "$ai_generation",
                    "trace_id": "failed-late",
                    "minutes": 3,
                    "properties": {"$ai_is_error": True},
                },
                {"event": "$ai_generation", "trace_id": "healthy-mid", "minutes": 2},
                {
                    "event": "$ai_generation",
                    "trace_id": "failed-early",
                    "minutes": 1,
                    "properties": {"$ai_is_error": True},
                },
                {"event": "$ai_generation", "trace_id": "healthy-early", "minutes": 0},
            ],
        )
        selection = self._selection(quick_filter=quick_filter)

        assert [position.trace_id for position in self._page_through(limit=1, selection=selection)] == expected
        first = load_rows_after(self.team, self.user, selection, after=None, take=1)
        assert first.counts == SelectionCounts(total=5, errors=2, feedback=0)

    def test_window_bounds_keep_their_microseconds(self) -> None:
        buffer_minutes = CAPTURE_BUFFER // timedelta(minutes=1)
        seed(
            self.team,
            [
                {"event": "$ai_generation", "trace_id": "at-window-end", "minutes": 60},
                {"event": "$ai_generation", "trace_id": "error-at-read-end", "minutes": 58},
                {
                    "event": "$ai_span",
                    "trace_id": "error-at-read-end",
                    "minutes": 60 + buffer_minutes,
                    "properties": {"$ai_is_error": True},
                },
                {"event": "$ai_generation", "trace_id": "error-past-read-end", "minutes": 59},
                {
                    "event": "$ai_span",
                    "trace_id": "error-past-read-end",
                    "minutes": 60 + buffer_minutes,
                    "microseconds": 1,
                    "properties": {"$ai_is_error": True},
                },
            ],
        )
        selection = self._selection(date_to=60)
        assert selection.window.end.microsecond != 0

        page = load_rows_after(self.team, self.user, selection, after=None, take=10)

        assert [position.trace_id for position in page.rows.positions] == [
            "at-window-end",
            "error-past-read-end",
            "error-at-read-end",
        ]
        assert page.counts == SelectionCounts(total=3, errors=1, feedback=0)

    def test_counts_ignore_the_cursor(self) -> None:
        seed(
            self.team,
            [
                {"event": "$ai_generation", "trace_id": "first", "minutes": 2, "properties": {"$ai_is_error": True}},
                {"event": "$ai_generation", "trace_id": "second", "minutes": 1},
                {"event": "$ai_generation", "trace_id": "third", "minutes": 0},
                {"event": "$ai_metric", "trace_id": "third", "minutes": 0},
            ],
        )
        selection = self._selection()

        first = load_rows_after(self.team, self.user, selection, after=None, take=1)
        second = load_rows_after(self.team, self.user, selection, after=first.rows.positions[-1], take=1)

        assert [position.trace_id for position in second.rows.positions] == ["second"]
        assert first.counts == second.counts == SelectionCounts(total=3, errors=1, feedback=1)

    def test_a_trace_id_with_awkward_characters_selects(self) -> None:
        # No quote or backslash: those depend on production's materialized trace id column, which tests do not have.
        trace_id = "a,b'c/d #%"
        seed(self.team, [{"event": "$ai_generation", "trace_id": trace_id, "minutes": 0}])

        page = load_rows_after(self.team, self.user, self._selection(), after=None, take=10)

        assert page.rows.positions == (TracePosition(trace_id=trace_id, first_timestamp=T0),)

    def test_trace_ids_stay_text_when_the_project_types_them_as_numbers(self) -> None:
        PropertyDefinition.objects.create(
            team=self.team, name="$ai_trace_id", property_type="Numeric", type=PropertyDefinition.Type.EVENT
        )
        seed(
            self.team,
            [
                {"event": "$ai_generation", "trace_id": "001", "minutes": 1},
                {"event": "$ai_generation", "trace_id": "1", "minutes": 0},
            ],
        )

        page = load_rows_after(self.team, self.user, self._selection(), after=None, take=10)

        assert [position.trace_id for position in page.rows.positions] == ["001", "1"]

    @parameterized.expand(
        [
            ("listing", {}),
            ("searching", {"search": "invoice"}),
            ("one session", {"session_id": "session-1", "order": "oldest_first"}),
        ]
    )
    def test_another_teams_traces_never_select(self, _name: str, scope: dict[str, Any]) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other organization"))
        seed(
            other_team,
            [
                {
                    "event": "$ai_generation",
                    "trace_id": "foreign",
                    "minutes": 0,
                    "properties": {"$ai_input": "Send the invoice", "$ai_session_id": "session-1"},
                }
            ],
        )

        page = load_rows_after(self.team, self.user, self._selection(**scope), after=None, take=10)

        assert page.rows.positions == ()
        assert page.counts in (None, SelectionCounts(total=0, errors=0, feedback=0))

    def test_a_search_combines_with_a_filter_only_the_events_table_resolves(self) -> None:
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org-a", properties={"plan": "enterprise"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org-b", properties={"plan": "free"})
        seed(
            self.team,
            [
                {
                    "event": "$ai_generation",
                    "trace_id": "term-in-enterprise",
                    "minutes": 0,
                    "properties": {"$ai_input": "Send the invoice", "$group_0": "org-a"},
                },
                {
                    "event": "$ai_generation",
                    "trace_id": "term-in-free",
                    "minutes": 1,
                    "properties": {"$ai_input": "Send the invoice", "$group_0": "org-b"},
                },
                {
                    "event": "$ai_generation",
                    "trace_id": "enterprise-without-term",
                    "minutes": 2,
                    "properties": {"$ai_input": "Hello", "$group_0": "org-a"},
                },
            ],
        )
        selection = self._selection(
            search="invoice",
            properties=[
                {"type": "group", "key": "plan", "value": "enterprise", "operator": "exact", "group_type_index": 0}
            ],
        )

        page = load_rows_after(self.team, self.user, selection, after=None, take=10)

        assert [position.trace_id for position in page.rows.positions] == ["term-in-enterprise"]

    def test_a_person_scoped_search_keeps_traces_stored_under_a_merged_person(self) -> None:
        identified, anonymous, other = (
            "00000000-0000-4000-8000-00000000000a",
            "00000000-0000-4000-8000-00000000000b",
            "00000000-0000-4000-8000-00000000000c",
        )
        seed(
            self.team,
            [
                {
                    "event": "$ai_generation",
                    "trace_id": "after-identify",
                    "minutes": 2,
                    "distinct_id": "identified-user",
                    "person_id": identified,
                    "properties": {"$ai_input": "Send the invoice"},
                },
                {
                    "event": "$ai_generation",
                    "trace_id": "before-identify",
                    "minutes": 1,
                    "distinct_id": "anonymous-user",
                    "person_id": anonymous,
                    "properties": {"$ai_input": "Draft the invoice"},
                },
                {
                    "event": "$ai_generation",
                    "trace_id": "other-person",
                    "minutes": 0,
                    "distinct_id": "other-user",
                    "person_id": other,
                    "properties": {"$ai_input": "Pay the invoice"},
                },
            ],
        )
        create_person_id_override_by_distinct_id("anonymous-user", "identified-user", self.team.pk)

        page = load_rows_after(
            self.team, self.user, self._selection(search="invoice", person_id=identified), after=None, take=10
        )

        assert [position.trace_id for position in page.rows.positions] == ["after-identify", "before-identify"]

    @parameterized.expand([("in the selection", False), ("in the test account filters", True)])
    def test_a_hogql_filter_can_read_a_saved_view(self, _name: str, as_test_account_filter: bool) -> None:
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="chosen_traces",
            query={"kind": "HogQLQuery", "query": "SELECT 'chosen' AS trace_id"},
            columns={"trace_id": "String"},
        )
        seed(
            self.team,
            [
                {"event": "$ai_generation", "trace_id": "chosen", "minutes": 0},
                {"event": "$ai_generation", "trace_id": "other", "minutes": 1},
            ],
        )
        hogql_filter = {"type": "hogql", "key": "properties.$ai_trace_id IN (SELECT trace_id FROM chosen_traces)"}
        if as_test_account_filter:
            self.team.test_account_filters = [hogql_filter]
            self.team.save()
        selection = self._selection(
            properties=[] if as_test_account_filter else [hogql_filter], filter_test_accounts=as_test_account_filter
        )

        page = load_rows_after(self.team, self.user, selection, after=None, take=10)

        assert [position.trace_id for position in page.rows.positions] == ["chosen"]

    @parameterized.expand(
        [
            ("list page", None, "after", SELECTION_QUERY_NAME),
            ("session page", "session-1", "after", "ai_session_traces_selection"),
            ("session page before a bound", "session-1", "before", "ai_session_traces_selection_before"),
            ("session page around a trace", "session-1", "around", "ai_session_traces_selection_around"),
        ]
    )
    def test_each_read_is_tagged_with_its_own_name(
        self, _name: str, session_id: str | None, read: str, expected_name: str
    ) -> None:
        comments: list[dict[str, Any]] = []
        selection = self._selection(session_id=session_id)
        reads: dict[str, Callable[[], object]] = {
            "after": lambda: load_rows_after(self.team, self.user, selection, after=None, take=10),
            "before": lambda: load_rows_before(
                self.team, self.user, selection, before=TracePosition(trace_id="t1", first_timestamp=T0), take=10
            ),
            "around": lambda: load_rows_around(
                self.team, self.user, selection, trace_id="t1", takes=AroundTakes(before=1, from_anchor=2)
            ),
        }

        def record_tags(execute: Any, query: str, *args: Any, **kwargs: Any) -> Any:
            comments.append(json.loads((kwargs.get("settings") or {}).get("log_comment", "{}")))
            return execute(query, *args, **kwargs)

        with patch_clickhouse_client_execute(record_tags):
            reads[read]()

        assert [(tags.get("name"), tags.get("product")) for tags in comments if tags.get("name")] == [
            (expected_name, "llm_analytics")
        ]

    def test_a_read_past_its_deadline_fails_instead_of_returning_partial_counts(self) -> None:
        selection_queries: list[str] = []

        def record_query(execute: Any, query: str, *args: Any, **kwargs: Any) -> Any:
            tags = json.loads((kwargs.get("settings") or {}).get("log_comment", "{}"))
            if tags.get("name") == SELECTION_QUERY_NAME:
                selection_queries.append(query)
            return execute(query, *args, **kwargs)

        with patch_clickhouse_client_execute(record_query):
            load_rows_after(self.team, self.user, self._selection(), after=None, take=10)

        [selection_query] = selection_queries
        assert "timeout_overflow_mode='throw'" in selection_query

    def _seed_five_session_traces(self) -> None:
        seed(
            self.team,
            [
                {
                    "event": "$ai_generation",
                    "trace_id": f"t{index + 1}",
                    "minutes": index,
                    "properties": {"$ai_session_id": "session-1"},
                }
                for index in range(5)
            ],
        )
        seed(
            self.team,
            [
                {
                    "event": "$ai_generation",
                    "trace_id": "elsewhere",
                    "minutes": 9,
                    "properties": {"$ai_session_id": "session-2"},
                }
            ],
        )

    @parameterized.expand(
        [
            ("oldest first", "oldest_first", "t5", ["t4", "t3"]),
            ("newest first", "newest_first", "t1", ["t2", "t3"]),
            ("bound no longer held", "oldest_first", "gone", ["t5", "t4"]),
        ]
    )
    def test_rows_before_read_back_from_the_bound(
        self, _name: str, order: str, bound: str, expected: list[str]
    ) -> None:
        self._seed_five_session_traces()
        selection = self._selection(session_id="session-1", order=order)
        minutes = {"t1": 0, "t5": 4, "gone": 30}[bound]

        rows = load_rows_before(
            self.team,
            self.user,
            selection,
            before=TracePosition(trace_id=bound, first_timestamp=T0 + timedelta(minutes=minutes)),
            take=2,
        )

        assert [position.trace_id for position in rows.positions] == expected

    @parameterized.expand(
        [("from the start", None, None), ("past a bound", "t2", "t2"), ("past a gone bound", "zz-gone", "t2")]
    )
    def test_rows_after_carry_the_row_before_the_page(
        self, _name: str, bound: str | None, expected_previous: str | None
    ) -> None:
        self._seed_five_session_traces()
        selection = self._selection(session_id="session-1", order="oldest_first")
        minutes = {"t2": 1, "zz-gone": 1}
        after = TracePosition(trace_id=bound, first_timestamp=T0 + timedelta(minutes=minutes[bound])) if bound else None

        read = load_rows_after(self.team, self.user, selection, after=after, take=2)

        assert (read.rows.previous.trace_id if read.rows.previous else None, read.counts) == (expected_previous, None)

    def test_a_session_page_reads_only_the_events_that_name_the_session(self) -> None:
        seed(
            self.team,
            [
                {
                    "event": "$ai_generation",
                    "trace_id": f"t{index:02d}",
                    "minutes": index,
                    "properties": {"$ai_session_id": "session-1"},
                }
                for index in range(30)
            ],
        )
        selection = self._selection(session_id="session-1", order="oldest_first")

        with self.capture_select_queries() as queries:
            read = load_rows_after(self.team, self.user, selection, after=None, take=3)

        [query] = queries
        assert "globalIn" not in query and "GLOBAL IN" not in query
        assert [position.trace_id for position in read.rows.positions] == ["t00", "t01", "t02"]

    @parameterized.expand(
        [
            ("anchor in the session", "t3", ["t2", "t1"], ["t3", "t4", "t5"]),
            ("anchor in another session", "elsewhere", [], ["t1", "t2", "t3"]),
        ]
    )
    def test_rows_around_read_both_sides_of_the_anchor(
        self, _name: str, anchor: str, before: list[str], from_anchor: list[str]
    ) -> None:
        self._seed_five_session_traces()
        selection = self._selection(session_id="session-1", order="oldest_first")

        rows = load_rows_around(
            self.team, self.user, selection, trace_id=anchor, takes=AroundTakes(before=2, from_anchor=3)
        )

        assert (
            [position.trace_id for position in rows.before],
            [position.trace_id for position in rows.from_anchor],
        ) == (before, from_anchor)

    def test_rows_around_keep_the_row_past_a_full_page(self) -> None:
        seed(
            self.team,
            [
                {
                    "event": "$ai_generation",
                    "trace_id": f"t{index:03d}",
                    "minutes": 0,
                    "microseconds": index * 1000,
                    "properties": {"$ai_session_id": "session-1"},
                }
                for index in range(101)
            ],
        )
        selection = self._selection(session_id="session-1", order="oldest_first")

        rows = load_rows_around(self.team, self.user, selection, trace_id="t000", takes=around_takes(100))

        next_after = page_around(rows, 100).next_after
        assert next_after is not None and next_after.trace_id == "t099"


def test_a_filter_hogql_cannot_express_is_a_selection_error() -> None:
    selection = TraceSelection(
        window=TraceWindow(start=T0, end=T0 + timedelta(hours=1)),
        properties=(
            _PROPERTY_FILTER.validate_python(
                {"type": "element", "key": "selector", "value": "button", "operator": "icontains"}
            ),
        ),
    )

    with pytest.raises(InvalidTraceSelectionError):
        load_rows_after(Team(), None, selection, after=None, take=10)


@pytest.mark.parametrize(
    "prop, expected",
    [
        ({"type": "hogql", "key": "1 = 1"}, True),
        ({"type": "person", "key": "$virt_revenue", "value": 10, "operator": "gt"}, True),
        ({"type": "group", "key": "$virt_mrr", "value": 10, "operator": "gt", "group_type_index": 0}, True),
        ({"type": "person", "key": "email", "value": "user@example.com", "operator": "exact"}, False),
    ],
)
def test_a_filter_on_a_virtual_revenue_property_needs_the_full_catalog(prop: dict[str, Any], expected: bool) -> None:
    assert _reads_beyond_posthog_tables(prop) is expected
