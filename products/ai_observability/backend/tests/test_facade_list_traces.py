from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from posthog.models import Team
from posthog.models.user import User

from products.ai_observability.backend.facade import api, contracts
from products.ai_observability.backend.logic.traces import trace_queries
from products.ai_observability.backend.logic.traces.events_fallback import FallbackWindow
from products.ai_observability.backend.logic.traces.preview_queries import PREVIEW_SOURCE_MAX_BYTES
from products.ai_observability.backend.logic.traces.trace_queries import PageTraceRows
from products.ai_observability.backend.logic.traces.trace_selection import TraceSelection, TraceWindow
from products.ai_observability.backend.models.review_queues import ReviewQueue, ReviewQueueItem
from products.ai_observability.backend.models.trace_reviews import TraceReview

from .presentation.views.trace_fixtures import TraceEvents
from .property_access import hide_event_property

STARTED_AT = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
SELECTION = TraceSelection(
    window=TraceWindow(start=STARTED_AT - timedelta(hours=1), end=STARTED_AT + timedelta(hours=1))
)
OVERVIEW_FIELDS = set(contracts.TraceOverview.model_fields)


class TestListTraces(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.events = TraceEvents(self.team, start=STARTED_AT)

    def _list(
        self, *, selection: TraceSelection = SELECTION, cursor: str | None = None, limit: int = 50
    ) -> contracts.TraceList:
        return api.load_trace_list(self.team, self.user, selection, cursor=cursor, limit=limit)()

    def test_a_row_carries_what_the_trace_read_carries(self) -> None:
        self.events.add(
            "trace-1", event="$ai_trace", properties={"$ai_trace_name": "Answer billing question", "$ai_latency": 4.2}
        )
        self.events.add(
            "trace-1",
            minutes=1,
            properties={
                "$ai_session_id": "session-1",
                "$ai_input_tokens": 120,
                "$ai_output_tokens": 30,
                "$ai_total_cost_usd": 0.25,
                "$ai_latency": 1.5,
            },
        )
        self.events.add(
            "trace-1",
            minutes=2,
            properties={
                "$ai_input_tokens": 80,
                "$ai_output_tokens": 0,
                "$ai_total_cost_usd": 0.5,
                "$ai_latency": 2.0,
                "$ai_is_error": True,
                "$ai_error": "Rate limit reached",
            },
        )
        self.events.seed()

        [item] = self._list().items
        trace = api.get_trace(self.team, self.user, "trace-1", None)

        assert (item.name, item.session_id, item.error_count) == ("Answer billing question", "session-1", 1)
        assert item.model_dump(include=OVERVIEW_FIELDS) == trace.model_dump(include=OVERVIEW_FIELDS)
        assert item.default_node_id == trace.default_node_id
        assert (item.first_error, item.has_error) == ("Rate limit reached", True)

    def test_rows_keep_the_selections_order(self) -> None:
        self.events.seed_traces("oldest", "middle", "newest")

        assert [item.id for item in self._list().items] == ["newest", "middle", "oldest"]

    def test_counts_come_with_the_first_page_only(self) -> None:
        self.events.add("errored", properties={"$ai_is_error": True})
        self.events.add("plain", minutes=1)
        self.events.add("rated", minutes=2)
        self.events.add("rated", event="$ai_feedback", minutes=2)
        self.events.seed()

        first = self._list(limit=2)
        assert first.next_cursor is not None
        second = self._list(cursor=first.next_cursor, limit=2)

        assert first.counts == contracts.TraceListCounts(total=3, errors=1, feedback=1)
        assert second.counts is None

    def test_a_trace_with_only_feedback_is_not_listed(self) -> None:
        self.events.add("answered")
        self.events.add("feedback-only", event="$ai_feedback", minutes=1)
        self.events.seed()

        listed = self._list()

        assert [item.id for item in listed.items] == ["answered"]
        assert listed.counts == contracts.TraceListCounts(total=1, errors=0, feedback=0)

    def test_an_empty_selection_lists_nothing(self) -> None:
        assert self._list() == contracts.TraceList(
            items=[], counts=contracts.TraceListCounts(total=0, errors=0, feedback=0), next_cursor=None
        )

    def test_next_cursor_walks_every_trace_once(self) -> None:
        trace_ids = [f"trace-{index}" for index in range(5)]
        self.events.seed_traces(*trace_ids)

        seen: list[str] = []
        cursor: str | None = None
        # Bounded, so a cursor that keeps handing back earlier traces fails instead of paging forever.
        for _ in range(5):
            page = self._list(cursor=cursor, limit=2)
            seen += [item.id for item in page.items]
            cursor = page.next_cursor
            if cursor is None:
                break

        assert (seen, cursor) == (list(reversed(trace_ids)), None)

    def test_a_trace_selected_but_with_no_rows_is_left_out(self) -> None:
        self.events.seed_traces("oldest", "middle", "newest")

        def without_middle(
            team: Team, user: User, trace_ids: Sequence[str], window: FallbackWindow
        ) -> dict[str, PageTraceRows]:
            loaded = trace_queries.load_traces_rows(team, user, trace_ids, window)
            return {trace_id: rows for trace_id, rows in loaded.items() if trace_id != "middle"}

        with patch.object(api, "load_traces_rows", side_effect=without_middle):
            items = self._list().items

        assert [item.id for item in items] == ["newest", "oldest"]

    def test_a_capped_trace_reports_partial_totals_and_no_default_step(self) -> None:
        for minutes in range(3):
            self.events.add("big", minutes=minutes, properties={"$ai_input_tokens": 10})
        self.events.add("small", properties={"$ai_input_tokens": 10})
        self.events.seed()

        with patch.object(trace_queries, "PAGE_ROW_CAP_PER_TRACE", 2):
            items = self._list().items

        assert {item.id: (item.totals_partial, item.totals.input_tokens, item.default_node_id) for item in items} == {
            "big": (True, 20, None),
            "small": (False, 10, "00000000-0000-4000-8000-000000000003"),
        }

    def test_a_support_trace_is_marked(self) -> None:
        self.events.add("support", properties={"ai_support_impersonated": True})
        self.events.add("customer", minutes=1)
        self.events.seed()

        items = self._list(selection=TraceSelection(window=SELECTION.window, include_support_traces=True)).items

        assert {item.id: item.is_support_trace for item in items} == {"support": True, "customer": False}

    def test_review_state_rides_in_the_row(self) -> None:
        self.events.seed_traces("reviewed", "queued", "untouched")
        TraceReview.objects.create(team=self.team, trace_id="reviewed", reviewed_by=self.user, created_by=self.user)
        queue = ReviewQueue.objects.create(team=self.team, name="Support QA", created_by=self.user)
        item = ReviewQueueItem.objects.create(team=self.team, queue=queue, trace_id="queued", created_by=self.user)

        reviews = {row.id: row.review for row in self._list().items}

        reviewed, queued = reviews["reviewed"], reviews["queued"]
        assert reviewed is not None and reviewed.review is not None and reviewed.queue is None
        assert queued == contracts.TraceReviewStatus(
            review=None,
            queue=contracts.TraceReviewQueueAssignment(id=str(queue.id), name="Support QA", item_id=str(item.id)),
        )
        assert reviews["untouched"] is None

    def test_a_bad_cursor_raises_from_the_load(self) -> None:
        with pytest.raises(api.InvalidTraceCursorError):
            api.load_trace_list(self.team, self.user, SELECTION, cursor="not-a-cursor", limit=50)

    def test_a_page_loads_in_two_clickhouse_reads_and_builds_with_none(self) -> None:
        self.events.seed_traces("older", "newer")

        with self.capture_select_queries() as loading:
            build = api.load_trace_list(self.team, self.user, SELECTION, cursor=None, limit=50)
        with self.capture_select_queries() as building:
            items = build().items

        assert (len(loading), building, [item.id for item in items]) == (2, [], ["newer", "older"])


def _chat(question: str, answer: str) -> dict[str, object]:
    return {
        "$ai_input": [{"role": "system", "content": "Be brief."}, {"role": "user", "content": question}],
        "$ai_output_choices": [{"role": "assistant", "content": answer}],
    }


class TestTracePreviews(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.events = TraceEvents(self.team, start=STARTED_AT)

    def _previews(self, *trace_ids: str) -> list[contracts.TracePreview]:
        return api.load_trace_previews(self.team, self.user, trace_ids)().items

    def _preview(
        self,
        trace_id: str,
        input: str | None,
        output: str | None,
        *,
        input_missing_reason: contracts.TracePreviewMissingReason | None = None,
    ) -> contracts.TracePreview:
        return contracts.TracePreview(
            trace_id=trace_id,
            input=input,
            output=output,
            input_missing_reason=input_missing_reason,
            output_missing_reason=None,
        )

    def test_a_page_previews_each_requested_trace_once_in_request_order(self) -> None:
        self.events.add("chat", properties=_chat("q" * 250, "a" * 250))
        self.events.add(
            "oversized",
            event="$ai_trace",
            properties={
                "$ai_input_state": {"document": "x" * (PREVIEW_SOURCE_MAX_BYTES + 1)},
                "$ai_output_state": [{"role": "assistant", "content": "Summarized."}],
            },
        )
        self.events.seed()

        assert self._previews("chat", "unknown", "oversized", "chat") == [
            self._preview("chat", "q" * 200, "a" * 200),
            self._preview("unknown", None, None),
            self._preview(
                "oversized", None, "Summarized.", input_missing_reason=contracts.TracePreviewMissingReason.TOO_LARGE
            ),
        ]

    def test_no_message_older_than_an_unreadable_one_is_previewed(self) -> None:
        oversized = {"role": "user", "content": "x" * (PREVIEW_SOURCE_MAX_BYTES + 1)}
        reply = {"role": "assistant", "content": "Let me check."}
        small = {"role": "user", "content": "Where is my parcel?"}
        answer = [{"role": "assistant", "content": "On its way."}]
        self.events.add(
            "unreadable-last", properties={"$ai_input": [small, reply, oversized], "$ai_output_choices": answer}
        )
        self.events.add(
            "unreadable-first", properties={"$ai_input": [oversized, reply, small], "$ai_output_choices": answer}
        )
        self.events.seed()

        assert self._previews("unreadable-last", "unreadable-first") == [
            self._preview(
                "unreadable-last",
                None,
                "On its way.",
                input_missing_reason=contracts.TracePreviewMissingReason.TOO_LARGE,
            ),
            self._preview("unreadable-first", "Where is my parcel?", "On its way."),
        ]

    def test_building_the_loaded_previews_runs_no_clickhouse_query_and_builds_the_normalizer_once(self) -> None:
        self.events.add("first", properties=_chat("Where is my parcel?", "On its way."))
        self.events.add("second", properties=_chat("Can I return it?", "Within 30 days."))
        self.events.seed()

        with self.capture_select_queries() as loading:
            build = api.load_trace_previews(self.team, self.user, ["first", "second"])
        with self.capture_select_queries() as building, CaptureQueriesContext(connection) as postgres:
            items = build().items

        recipe_reads = [query for query in postgres.captured_queries if "ai_observability_parserrecipe" in query["sql"]]
        assert (len(loading), building, len(recipe_reads)) == (2, [], 1)
        assert [item.output for item in items] == ["On its way.", "Within 30 days."]

    def test_a_restricted_input_previews_as_null(self) -> None:
        self.events.add("chat", properties=_chat("Where is my parcel?", "On its way."))
        self.events.seed()
        hide_event_property(self.team, self.user, "$ai_input")

        assert self._previews("chat") == [self._preview("chat", None, "On its way.")]

    def test_the_message_comes_from_the_first_generation_and_the_answer_from_state_or_the_latest(self) -> None:
        for trace_id, state_answer in (("with-state", "Answered from the state."), ("without-state", None)):
            if state_answer is not None:
                self.events.add(
                    trace_id,
                    event="$ai_trace",
                    properties={"$ai_output_state": [{"role": "assistant", "content": state_answer}]},
                )
            self.events.add(trace_id, minutes=1, properties=_chat("Opening question", "First answer"))
            self.events.add(trace_id, minutes=2, properties=_chat("Follow-up question", "Final answer"))
        self.events.seed()

        assert self._previews("with-state", "without-state") == [
            self._preview("with-state", "Opening question", "Answered from the state."),
            self._preview("without-state", "Opening question", "Final answer"),
        ]
