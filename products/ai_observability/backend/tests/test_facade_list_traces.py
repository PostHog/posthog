from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from posthog.models import Team
from posthog.models.user import User
from posthog.test.persons import create_person

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

        assert {
            item.id: (
                item.totals_partial,
                item.cost_and_latency_partial,
                item.totals.input_tokens,
                item.default_node_id,
            )
            for item in items
        } == {
            "big": (True, False, 20, None),
            "small": (False, False, 10, "00000000-0000-4000-8000-000000000003"),
        }

    def test_a_trace_read_from_the_shared_table_from_the_edge_of_the_read_reports_partial_totals_cost_and_latency(
        self,
    ) -> None:
        read_start_minutes = int((SELECTION.window.read_bounds().start - STARTED_AT) / timedelta(minutes=1))
        for trace_id, first_minutes in (
            ("aged-at-edge", read_start_minutes),
            ("aged-inside", 0),
            ("kept-at-edge", read_start_minutes),
        ):
            self.events.add(trace_id, minutes=first_minutes)
            self.events.add(trace_id, minutes=1)
        self.events.seed(aged_out={"aged-at-edge", "aged-inside"})

        items = self._list().items

        assert {item.id: (item.totals_partial, item.cost_and_latency_partial) for item in items} == {
            "aged-at-edge": (True, True),
            "aged-inside": (False, False),
            "kept-at-edge": (False, False),
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


class TestTracePeople(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.events = TraceEvents(self.team, start=STARTED_AT)

    def test_a_page_labels_each_trace_by_its_person_in_request_order(self) -> None:
        create_person(team=self.team, distinct_ids=["ada-id"], properties={"email": "ada@example.com"})
        create_person(team=self.team, distinct_ids=["grace-id"], properties={"name": "Grace"})
        create_person(team=self.team, distinct_ids=["anonymous-id"], properties={"plan": "pro"})
        self.events.add("ada", distinct_id="ada-id")
        self.events.add("grace", minutes=1, distinct_id="grace-id")
        self.events.add("anonymous", minutes=2, distinct_id="anonymous-id")
        self.events.add("no-distinct-id", minutes=3, distinct_id="")
        self.events.seed()

        people = api.load_trace_people(
            self.team,
            self.user,
            ["grace", "unknown", "ada", "anonymous", "no-distinct-id", "grace"],
            earliest=STARTED_AT,
            latest=STARTED_AT + timedelta(minutes=3),
        )

        assert people.items == [
            contracts.TracePersonItem(
                trace_id="grace", person=contracts.TracePerson(distinct_id="grace-id", label="Grace")
            ),
            contracts.TracePersonItem(trace_id="unknown", person=None),
            contracts.TracePersonItem(
                trace_id="ada", person=contracts.TracePerson(distinct_id="ada-id", label="ada@example.com")
            ),
            contracts.TracePersonItem(
                trace_id="anonymous", person=contracts.TracePerson(distinct_id="anonymous-id", label="anonymous-id")
            ),
            contracts.TracePersonItem(trace_id="no-distinct-id", person=None),
        ]

    @parameterized.expand(
        [
            (
                "labelled by the project's display name",
                "user-1",
                contracts.TracePerson(distinct_id="user-1", label="Ada"),
            ),
            ("no distinct id", "", None),
        ]
    )
    def test_a_page_and_the_trace_read_give_a_trace_the_same_person(
        self, _name: str, distinct_id: str, expected: contracts.TracePerson | None
    ) -> None:
        self.team.person_display_name_properties = ["nickname"]
        self.team.save()
        create_person(team=self.team, distinct_ids=["user-1"], properties={"nickname": "Ada", "email": "a@example.com"})
        self.events.add("trace-1", distinct_id=distinct_id)
        self.events.seed()

        [item] = api.load_trace_people(self.team, self.user, ["trace-1"], earliest=STARTED_AT, latest=STARTED_AT).items
        trace = api.get_trace(self.team, self.user, "trace-1", None)

        assert (item.person, trace.person) == (expected, expected)


class TestTraceSentiments(ClickhouseTestMixin, BaseTest):
    def test_a_page_gets_one_sentiment_item_per_trace_in_request_order(self) -> None:
        events = TraceEvents(self.team, start=STARTED_AT)
        events.add("rated")
        events.add(
            "rated",
            event="$ai_evaluation",
            properties={
                "$ai_evaluation_runtime": "sentiment",
                "$ai_target_event_id": "generation-1",
                "$ai_sentiment_label": "positive",
                "$ai_sentiment_score": 0.9,
                "$ai_sentiment_scores": {"positive": 0.9, "neutral": 0.08, "negative": 0.02},
                "$ai_sentiment_message_count": 1,
            },
        )
        events.add("unrated", minutes=1)
        events.seed()

        sentiments = api.load_trace_sentiments(
            self.team,
            self.user,
            ["unrated", "rated", "unknown", "unrated"],
            earliest=STARTED_AT,
            latest=STARTED_AT + timedelta(minutes=1),
        )

        assert sentiments.items == [
            contracts.TraceSentimentItem(trace_id="unrated", sentiment=None),
            contracts.TraceSentimentItem(
                trace_id="rated", sentiment=contracts.TraceSentiment(label="positive", score=0.9)
            ),
            contracts.TraceSentimentItem(trace_id="unknown", sentiment=None),
        ]
