from datetime import timedelta
from typing import Any

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import EventPropertyFilter, PropertyOperator

from products.ai_observability.backend.logic.traces.session_selection_queries import (
    SessionPosition,
    SessionSelectionPage,
    decode_session_cursor,
    encode_session_cursor,
    load_session_page,
)
from products.ai_observability.backend.logic.traces.trace_selection import (
    InvalidTraceCursorError,
    InvalidTraceSelectionError,
    TraceSelection,
)

from .test_trace_selection_queries import at, seed, to_selection


def generation(trace_id: str, minutes: int, session_id: str | None, **properties: Any) -> dict[str, Any]:
    session = {} if session_id is None else {"$ai_session_id": session_id}
    return {
        "event": "$ai_generation",
        "trace_id": trace_id,
        "minutes": minutes,
        "properties": {**session, **properties},
    }


class TestSessionSelectionQueries(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.timezone = "Asia/Kolkata"
        self.team.save()

    def _selection(self, **overrides: Any) -> TraceSelection:
        return to_selection(self.team, {"date_from": -60, "date_to": 60, **overrides})

    def _page(self, after: SessionPosition | None = None, limit: int = 50, **overrides: Any) -> SessionSelectionPage:
        return load_session_page(self.team, self.user, self._selection(**overrides), after=after, limit=limit)

    def test_sessions_newest_activity_first(self) -> None:
        seed(
            self.team,
            [
                generation("t-old", 1, "quiet"),
                generation("t-long-start", 0, "busy"),
                generation("t-long-end", 9, "busy"),
                generation("t-mid", 5, "middle"),
            ],
        )

        page = self._page()

        assert page.session_ids == ("busy", "middle", "quiet")
        assert page.has_more is False
        assert page.last_position == SessionPosition(session_id="quiet", last_timestamp=at(1))

    def test_traces_without_session_are_skipped(self) -> None:
        seed(
            self.team,
            [
                generation("t-none", 5, None),
                generation("t-empty", 4, ""),
                generation("t-kept", 1, "kept"),
            ],
        )

        assert self._page().session_ids == ("kept",)

    def test_filters_pick_sessions_through_their_traces(self) -> None:
        seed(
            self.team,
            [
                generation("t-match", 1, "matching", flavour="vanilla"),
                generation("t-other", 2, "other", flavour="mint"),
            ],
        )
        flavour = EventPropertyFilter(key="flavour", value="vanilla", operator=PropertyOperator.EXACT)
        window = self._selection().window

        page = load_session_page(
            self.team, self.user, TraceSelection(window=window, properties=(flavour,)), after=None, limit=50
        )

        assert page.session_ids == ("matching",)

    def test_trace_with_two_session_ids_goes_to_first_non_empty(self) -> None:
        seed(
            self.team,
            [
                generation("t-two", 1, ""),
                generation("t-two", 2, "first"),
                generation("t-two", 3, "second"),
            ],
        )

        assert self._page().session_ids == ("first",)

    def test_paging_by_cursor(self) -> None:
        seed(
            self.team,
            [
                generation("t-1", 4, "d"),
                generation("t-2", 3, "b"),
                generation("t-3", 3, "a"),
                generation("t-4", 1, "c"),
            ],
        )

        first = self._page(limit=2)
        second = self._page(after=first.last_position, limit=2)

        assert first.session_ids == ("d", "a")
        assert first.has_more is True
        assert second.session_ids == ("b", "c")
        assert second.has_more is False

    def test_empty_page_has_no_position(self) -> None:
        assert self._page() == SessionSelectionPage(session_ids=(), has_more=False, last_position=None)

    def test_a_session_scoped_selection_is_not_a_sessions_list(self) -> None:
        with pytest.raises(InvalidTraceSelectionError):
            self._page(session_id="busy")


class TestSessionCursor:
    def test_round_trips_a_position(self) -> None:
        position = SessionPosition(session_id="session-é", last_timestamp=at(3) + timedelta(microseconds=7))

        assert decode_session_cursor(encode_session_cursor(position)) == position

    @parameterized.expand([("not base64!",), ("W1wiYVwiLDFd",), ("WzEsMl0",)])
    def test_rejects_a_malformed_cursor(self, cursor: str) -> None:
        with pytest.raises(InvalidTraceCursorError):
            decode_session_cursor(cursor)
