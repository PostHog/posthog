from datetime import datetime

from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.models import User
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.event.util import bulk_create_events

from products.ai_observability.backend.logic.traces.node_contents_queries import load_trace_nodes

from ...property_access import hide_event_property
from .test_trace_queries import T0, TraceEventsMixin

SPAN = "00000000-0000-0000-0000-000000000001"
GENERATION = "00000000-0000-0000-0000-000000000002"
TRACE_EVENT = "00000000-0000-0000-0000-000000000003"
FEEDBACK = "00000000-0000-0000-0000-000000000004"
OTHER_TRACE_SPAN = "00000000-0000-0000-0000-000000000005"
QUESTION = [{"role": "user", "content": "Can I change my delivery address?"}]


class TestLoadTraceNodes(TraceEventsMixin, ClickhouseTestMixin, BaseTest):
    def _seed(self) -> None:
        bulk_create_ai_events(
            [
                self._event(SPAN, properties={"$ai_span_name": "plan"}),
                self._event(GENERATION, event="$ai_generation", properties={"$ai_input": QUESTION}),
                self._event(TRACE_EVENT, event="$ai_trace"),
                self._event(FEEDBACK, event="$ai_feedback"),
                self._event(OTHER_TRACE_SPAN, trace_id="trace-2"),
            ]
        )

    def test_reads_the_requested_steps_in_order_with_their_contents(self) -> None:
        self._seed()

        rows = load_trace_nodes(
            self.team,
            None,
            "trace-1",
            [GENERATION, TRACE_EVENT, FEEDBACK, OTHER_TRACE_SPAN, "not-a-uuid", SPAN.upper()],
            None,
        )

        assert [row.uuid for row in rows] == [GENERATION, SPAN]
        assert rows[0].properties["$ai_input"] == QUESTION

    def test_restricted_input_is_masked_for_the_reader(self) -> None:
        reader = User.objects.create_and_join(self.organization, "reader@example.com", "testtest")
        hide_event_property(self.team, reader, "$ai_input")
        self._seed()

        [owner_row] = load_trace_nodes(self.team, self.user, "trace-1", [GENERATION], None)
        [reader_row] = load_trace_nodes(self.team, reader, "trace-1", [GENERATION], None)

        assert owner_row.properties["$ai_input"] == QUESTION
        assert "$ai_input" not in reader_row.properties

    @parameterized.expand(
        [
            ("with a hint", [SPAN], T0, [SPAN]),
            ("without a hint", [SPAN], None, []),
            ("no ids", [], T0, []),
        ]
    )
    def test_falls_back_to_events_only_with_a_hint(
        self, _name: str, node_ids: list[str], timestamp_hint: datetime | None, expected: list[str]
    ) -> None:
        bulk_create_events([self._event(SPAN, properties={"$ai_span_name": "old"})])

        rows = load_trace_nodes(self.team, None, "trace-1", node_ids, timestamp_hint)

        assert [row.uuid for row in rows] == expected
