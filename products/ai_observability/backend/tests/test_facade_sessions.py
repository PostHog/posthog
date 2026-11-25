from collections.abc import Callable, Collection
from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.test import override_settings

from parameterized import parameterized

from posthog.test.persons import create_person

from products.ai_observability.backend.facade import api, contracts
from products.ai_observability.backend.logic.traces.trace_selection import (
    TracePosition,
    TraceSelection,
    TraceWindow,
    encode_cursor,
)

from .presentation.views.trace_fixtures import TraceEvents
from .property_access import hide_event_property

STARTED_AT = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
SELECTION = TraceSelection(
    window=TraceWindow(start=STARTED_AT - timedelta(hours=1), end=STARTED_AT + timedelta(hours=1))
)


def in_session(session_id: str, **properties: object) -> dict[str, object]:
    return {"$ai_session_id": session_id, **properties}


def chat(session_id: str, question: str, answer: str) -> dict[str, object]:
    return in_session(
        session_id,
        **{
            "$ai_input": [{"role": "user", "content": question}],
            "$ai_output_choices": [{"role": "assistant", "content": answer}],
        },
    )


def ids(items: Collection[contracts.TraceListItem]) -> list[str]:
    return [item.id for item in items]


@time_machine.travel(STARTED_AT + timedelta(days=1), tick=False)
class TestSessionList(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.events = TraceEvents(self.team, start=STARTED_AT)

    def _list(
        self, *, cursor: str | None = None, limit: int = 50, selection: TraceSelection = SELECTION
    ) -> contracts.SessionList:
        return api.load_session_list(self.team, self.user, selection, cursor=cursor, limit=limit)()

    def test_pages_sessions_by_last_activity_with_their_facts(self) -> None:
        self.events.add("a1", minutes=0, properties=in_session("session-a"))
        self.events.add("a2", minutes=10, properties=in_session("session-a"))
        self.events.add("b1", minutes=20, properties=in_session("session-b"))
        self.events.seed()

        first = self._list(limit=1)
        second = self._list(limit=1, cursor=first.next_cursor)

        assert [(item.id, item.turn_count) for item in [*first.items, *second.items]] == [
            ("session-b", 1),
            ("session-a", 2),
        ]
        assert second.next_cursor is None

    @parameterized.expand([("held in ai_events", ()), ("aged out of ai_events", ("early", "late"))])
    def test_facts_count_a_trace_from_before_the_list_range(self, _name: str, aged_out: tuple[str, ...]) -> None:
        self.events.add("early", minutes=-2 * 24 * 60, properties=in_session("session-a", **{"$ai_total_cost_usd": 1}))
        self.events.add("late", minutes=0, properties=in_session("session-a", **{"$ai_total_cost_usd": 2}))
        self.events.seed(aged_out=aged_out)

        (item,) = self._list().items

        assert (item.turn_count, item.totals.cost_usd, item.first_seen) == (
            2,
            3,
            STARTED_AT - timedelta(days=2),
        )

    def test_support_traces_follow_the_selection(self) -> None:
        self.events.add("a1", minutes=0, properties=in_session("session-a", ai_support_impersonated="true"))
        self.events.seed()
        with_support = TraceSelection(window=SELECTION.window, include_support_traces=True)

        assert self._list().items == []
        assert [item.id for item in self._list(selection=with_support).items] == ["session-a"]


@time_machine.travel(STARTED_AT + timedelta(days=1), tick=False)
class TestGetSession(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.events = TraceEvents(self.team, start=STARTED_AT)

    def _get(self, session_id: str, hint: datetime | None = None) -> contracts.SessionListItem | None:
        return api.get_session(self.team, self.user, session_id, timestamp_hint=hint)

    def test_an_aged_out_session_needs_the_hint(self) -> None:
        self.events.add("a1", minutes=0, properties=in_session("session-a"))
        self.events.seed(aged_out={"a1"})

        assert self._get("session-a") is None
        found = self._get("session-a", STARTED_AT)
        assert found is not None
        assert found.id == "session-a"


@time_machine.travel(STARTED_AT + timedelta(days=1), tick=False)
class TestSessionTurns(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.events = TraceEvents(self.team, start=STARTED_AT)

    def _load(
        self,
        session_id: str = "session-a",
        *,
        cursor: str | None = None,
        before_cursor: str | None = None,
        around: str | None = None,
        limit: int = 20,
    ) -> Callable[[], contracts.SessionTurnPage] | None:
        return api.load_session_turns(
            self.team,
            self.user,
            session_id,
            timestamp_hint=None,
            cursor=cursor,
            before_cursor=before_cursor,
            around=around,
            limit=limit,
        )

    def _turns(
        self,
        *,
        cursor: str | None = None,
        before_cursor: str | None = None,
        around: str | None = None,
        limit: int = 20,
    ) -> contracts.SessionTurnPage:
        build = self._load(cursor=cursor, before_cursor=before_cursor, around=around, limit=limit)
        assert build is not None
        return build()

    def _seed_session(self, count: int) -> None:
        for index in range(count):
            self.events.add(f"a{index + 1}", minutes=index, properties=in_session("session-a"))
        self.events.add("b1", minutes=count, properties=in_session("session-b"))
        self.events.seed()

    @parameterized.expand(
        [
            ("after a cursor", "after"),
            ("before a cursor", "before"),
            ("around a trace", "around"),
        ]
    )
    def test_a_turn_says_how_long_its_wait_was_and_the_silence_before_it_even_first_on_a_page(
        self, _name: str, read: str
    ) -> None:
        self.events.add("a1", minutes=0, properties=in_session("session-a", **{"$ai_latency": 2}))
        self.events.add("a2", minutes=5, properties=in_session("session-a", **{"$ai_latency": 12}))
        self.events.add("a3", minutes=6, properties=in_session("session-a"))
        self.events.seed()
        first, last = self._turns(limit=1), self._turns(around="a3", limit=1)
        reads: dict[str, Callable[[], contracts.SessionTurnPage]] = {
            "after": lambda: self._turns(cursor=first.next_cursor, limit=1),
            "before": lambda: self._turns(before_cursor=last.previous_cursor, limit=1),
            "around": lambda: self._turns(around="a2", limit=1),
        }

        page = reads[read]()

        assert [(item.id, item.wait_slow, item.silence_before_ms) for item in page.items] == [("a2", True, 298_000)]
        assert [(item.id, item.wait_slow, item.silence_before_ms) for item in first.items] == [("a1", False, None)]

    def test_a_page_before_the_first_turn_leads_back_to_it(self) -> None:
        self._seed_session(3)
        cursor = encode_cursor(TracePosition(trace_id="a1", first_timestamp=STARTED_AT))

        page = self._turns(before_cursor=cursor)
        following = self._turns(cursor=page.next_cursor, limit=1)

        assert (page.items, page.previous_cursor, ids(following.items)) == ([], None, ["a1"])

    def test_a_session_without_traces_is_not_found(self) -> None:
        self._seed_session(1)

        assert (self._load("missing"), self._load("missing", around="a1")) == (None, None)

    @parameterized.expand([("first page", None), ("around a trace", "a2")])
    def test_a_page_loads_in_two_clickhouse_reads_and_builds_with_none(self, _name: str, around: str | None) -> None:
        self._seed_session(3)

        with self.capture_select_queries() as loading:
            build = self._load(around=around)
        assert build is not None
        with self.capture_select_queries() as building:
            items = build().items

        assert (len(loading), building, ids(items)) == (2, [], ["a1", "a2", "a3"])


@time_machine.travel(STARTED_AT + timedelta(days=45), tick=False)
class TestOldSession(ClickhouseTestMixin, BaseTest):
    def test_turns_and_facts_read_from_an_old_hint_to_now(self) -> None:
        events = TraceEvents(self.team, start=STARTED_AT)
        for trace_id, days in (("first", 0), ("a-week-on", 8), ("recent", 20)):
            events.add(trace_id, minutes=days * 24 * 60, properties=in_session("session-a"))
        events.seed(aged_out={"first", "a-week-on"})

        build = api.load_session_turns(
            self.team,
            self.user,
            "session-a",
            timestamp_hint=STARTED_AT,
            cursor=None,
            before_cursor=None,
            around=None,
            limit=20,
        )
        session = api.get_session(self.team, self.user, "session-a", timestamp_hint=STARTED_AT)

        assert build is not None and session is not None
        assert (ids(build().items), session.turn_count) == (["first", "a-week-on", "recent"], 3)


@time_machine.travel(STARTED_AT + timedelta(days=45), tick=False)
class TestSessionTurnsWindow(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.events = TraceEvents(self.team, start=STARTED_AT)
        self.events.add("a1", properties=in_session("session-a"))
        self.events.seed(aged_out={"a1"})

    def _found(self, hint: datetime | None) -> bool:
        build = api.load_session_turns(
            self.team,
            self.user,
            "session-a",
            timestamp_hint=hint,
            cursor=None,
            before_cursor=None,
            around=None,
            limit=20,
        )
        return build is not None and ids(build().items) == ["a1"]

    @parameterized.expand(
        [
            ("past the default retention", 30, None, False),
            ("inside an extended retention", 60, None, True),
        ]
    )
    def test_turns_read_over_the_teams_retention_or_around_an_older_hint(
        self, _name: str, retention_days: int, hint: datetime | None, found: bool
    ) -> None:
        with override_settings(AI_EVENTS_RETENTION_DAYS_BY_TEAM={self.team.pk: retention_days}):
            assert self._found(hint) is found


@time_machine.travel(STARTED_AT + timedelta(days=1), tick=False)
class TestSessionPreviews(ClickhouseTestMixin, BaseTest):
    def test_a_session_is_titled_by_its_first_traces_message_in_request_order(self) -> None:
        events = TraceEvents(self.team, start=STARTED_AT)
        events.add("a2", minutes=1, properties=chat("session-a", "Second question", "Second answer"))
        events.add("a1", minutes=0, properties=chat("session-a", "First question", "First answer"))
        events.add("b-z", minutes=2, properties=chat("session-b", "From z", "Answer"))
        events.add("b-y", minutes=2, properties=chat("session-b", "From y", "Answer"))
        events.seed()

        with self.capture_select_queries() as loading:
            build = api.load_session_previews(self.team, self.user, ["session-b", "missing", "session-a", "session-b"])
        with self.capture_select_queries() as building:
            items = build().items

        assert [(item.session_id, item.input, item.input_missing_reason) for item in items] == [
            ("session-b", "From y", None),
            ("missing", None, None),
            ("session-a", "First question", None),
        ]
        assert (len(loading), building) == (3, [])

    def test_a_restricted_input_titles_as_null(self) -> None:
        events = TraceEvents(self.team, start=STARTED_AT)
        events.add("a1", properties=chat("session-a", "Where is my parcel?", "On its way."))
        events.seed()
        hide_event_property(self.team, self.user, "$ai_input")

        (item,) = api.load_session_previews(self.team, self.user, ["session-a"])().items

        assert (item.input, item.input_missing_reason) == (None, None)


@time_machine.travel(STARTED_AT + timedelta(days=1), tick=False)
class TestSessionPeople(ClickhouseTestMixin, BaseTest):
    def test_a_session_runs_for_its_first_traces_person(self) -> None:
        create_person(team=self.team, distinct_ids=["ada-id"], properties={"email": "ada@example.com"})
        events = TraceEvents(self.team, start=STARTED_AT)
        events.add("a2", minutes=1, properties=in_session("session-a"), distinct_id="bob-id")
        events.add("a1", minutes=0, properties=in_session("session-a"), distinct_id="ada-id")
        events.seed()

        people = api.load_session_people(self.team, self.user, ["missing", "session-a"])

        assert people.items == [
            contracts.SessionPersonItem(session_id="missing", person=None),
            contracts.SessionPersonItem(
                session_id="session-a", person=contracts.TracePerson(distinct_id="ada-id", label="ada@example.com")
            ),
        ]
