from datetime import timedelta

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from products.ai_observability.backend.logic.traces.preview_queries import PREVIEW_SOURCE_MAX_BYTES

from .trace_fixtures import T0, QuerySlotRecorder, TraceEvents, post_page_read

CHAT: dict[str, object] = {
    "$ai_input": [{"role": "user", "content": "Where is my parcel?"}],
    "$ai_output_choices": [{"role": "assistant", "content": "On its way."}],
}
OVERSIZED = "x" * (PREVIEW_SOURCE_MAX_BYTES + 1)


@time_machine.travel(T0 + timedelta(days=1), tick=False)
class TestTracePreviewsViewSet(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand(
        [
            ("browser session", None, "trace-1"),
            ("read key", ["llm_analytics:read"], "trace-1"),
            ("id with leading and trailing spaces", None, "  trace-1 "),
        ]
    )
    def test_previews_each_trace_on_a_page(self, _name: str, scopes: list[str] | None, trace_id: str) -> None:
        events = TraceEvents(self.team)
        events.add(trace_id, properties=CHAT)
        events.seed()

        response = post_page_read(self, "previews", {"trace_ids": [trace_id]}, scopes=scopes)

        assert (response.status_code, response.json()) == (
            200,
            {
                "items": [
                    {
                        "traceId": trace_id,
                        "input": "Where is my parcel?",
                        "output": "On its way.",
                        "inputMissingReason": None,
                        "outputMissingReason": None,
                    }
                ]
            },
        )

    def test_a_preview_too_large_to_read_says_why(self) -> None:
        events = TraceEvents(self.team)
        events.add("trace-1", properties={**CHAT, "$ai_output_choices": [{"role": "assistant", "content": OVERSIZED}]})
        events.seed()

        response = post_page_read(self, "previews", {"trace_ids": ["trace-1"]})

        assert response.json()["items"] == [
            {
                "traceId": "trace-1",
                "input": "Where is my parcel?",
                "output": None,
                "inputMissingReason": None,
                "outputMissingReason": "too_large",
            }
        ]

    def test_a_page_is_built_after_its_query_slot_is_released(self) -> None:
        events = TraceEvents(self.team)
        events.add("trace-1", properties=CHAT)
        events.seed()

        with QuerySlotRecorder().recording("load_trace_previews") as recorder:
            response = post_page_read(self, "previews", {"trace_ids": ["trace-1"]})

        assert (response.status_code, recorder.loaded_while_holding, recorder.built_while_holding) == (
            200,
            [True],
            [False],
        )
