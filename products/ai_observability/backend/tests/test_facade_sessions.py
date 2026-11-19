from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin

from products.ai_observability.backend.facade import api, contracts
from products.ai_observability.backend.logic.traces.trace_selection import TraceSelection, TraceWindow

from .presentation.views.trace_fixtures import TraceEvents

STARTED_AT = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
SELECTION = TraceSelection(
    window=TraceWindow(start=STARTED_AT - timedelta(hours=1), end=STARTED_AT + timedelta(hours=1))
)


def in_session(session_id: str, **properties: object) -> dict[str, object]:
    return {"$ai_session_id": session_id, **properties}


@time_machine.travel(STARTED_AT + timedelta(days=1), tick=False)
class TestSessionList(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.events = TraceEvents(self.team, start=STARTED_AT)

    def _list(
        self, *, cursor: str | None = None, limit: int = 50, selection: TraceSelection = SELECTION
    ) -> contracts.SessionList:
        return api.load_session_list(self.team, self.user, selection, cursor=cursor, limit=limit)()

    def test_pages_sessions_by_last_activity_with_whole_session_facts(self) -> None:
        self.events.add("a1", minutes=0, properties=in_session("session-a", **{"$ai_latency": 2}))
        self.events.add("a2", minutes=10, properties=in_session("session-a", **{"$ai_latency": 3}))
        self.events.add("b1", minutes=20, properties=in_session("session-b", **{"$ai_total_cost_usd": 0.5}))
        self.events.add("c1", minutes=30, properties={"$ai_latency": 1})
        self.events.seed()

        first = self._list(limit=1)
        second = self._list(limit=1, cursor=first.next_cursor)

        assert [item.id for item in first.items] == ["session-b"]
        assert first.items[0].totals.cost_usd == 0.5
        assert first.items[0].first_trace_id == "b1"
        assert [item.id for item in second.items] == ["session-a"]
        assert second.next_cursor is None
        assert second.items[0].turn_count == 2
        assert second.items[0].totals.latency_ms == 5000
        assert second.items[0].errored_turns == 0

    def test_a_session_found_only_in_events_is_read_through_the_list_window(self) -> None:
        self.events.add("a1", minutes=0, properties=in_session("session-a"))
        self.events.seed(aged_out={"a1"})

        listed = self._list()

        assert [item.id for item in listed.items] == ["session-a"]

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
        return api.get_session(self.team, self.user, session_id, hint=hint)

    def test_reads_a_session_with_its_facts(self) -> None:
        self.events.add("a1", minutes=0, properties=in_session("session-a"))
        self.events.add("a2", minutes=5, properties=in_session("session-a"))
        self.events.seed()

        session = self._get("session-a")

        assert session is not None
        assert (session.turn_count, session.first_trace_id) == (2, "a1")

    def test_an_unknown_session_is_none(self) -> None:
        assert self._get("missing") is None

    def test_an_aged_out_session_needs_the_hint(self) -> None:
        self.events.add("a1", minutes=0, properties=in_session("session-a"))
        self.events.seed(aged_out={"a1"})

        assert self._get("session-a") is None
        found = self._get("session-a", STARTED_AT)
        assert found is not None
        assert found.id == "session-a"


@time_machine.travel(STARTED_AT + timedelta(days=1), tick=False)
class TestHasSessions(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.events = TraceEvents(self.team, start=STARTED_AT)

    def test_is_false_without_a_session_id(self) -> None:
        self.events.add("t1")
        self.events.seed()

        assert api.has_sessions(self.team, self.user).has_sessions is False

    def test_is_true_with_a_session_id(self) -> None:
        self.events.add("t1", properties=in_session("session-a"))
        self.events.seed()

        assert api.has_sessions(self.team, self.user).has_sessions is True

    def test_ignores_sessions_older_than_the_retention(self) -> None:
        self.events.add("t1", minutes=-60 * 24 * 40, properties=in_session("session-a"))
        self.events.seed()

        assert api.has_sessions(self.team, self.user).has_sessions is False
