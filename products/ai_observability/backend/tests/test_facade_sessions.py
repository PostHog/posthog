from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

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
