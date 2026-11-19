from datetime import timedelta
from typing import TYPE_CHECKING

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from products.ai_observability.backend.facade.api import TRACE_TURNS_MAX_IDS
from products.ai_observability.backend.logic.traces.turn_queries import TURN_SIDE_MAX_BYTES

from .trace_fixtures import PAGE_BOUNDS, T0, QuerySlotRecorder, TraceEvents, post_page_read

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

CHAT: dict[str, object] = {
    "$ai_input": [{"role": "user", "content": "Where is my parcel?"}],
    "$ai_output_choices": [{"role": "assistant", "content": "On its way."}],
}


def post_turns(test: APIBaseTest, trace_ids: list[str], *, scopes: list[str] | None = None) -> "_MonkeyPatchedResponse":
    return post_page_read(test, "turns", {"trace_ids": trace_ids, **PAGE_BOUNDS}, scopes=scopes)


@time_machine.travel(T0 + timedelta(days=1), tick=False)
class TestTraceTurnsViewSet(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand([("browser session", None), ("read key", ["llm_analytics:read"])])
    def test_turns_returns_sides_in_request_order(self, _name: str, scopes: list[str] | None) -> None:
        events = TraceEvents(self.team)
        events.add("trace-1", properties=CHAT)
        events.add(
            "trace-2", minutes=1, properties={**CHAT, "$ai_output_choices": [{"role": "assistant", "content": "Soon."}]}
        )
        events.seed()

        response = post_turns(self, ["trace-2", "unknown", "trace-1"], scopes=scopes)

        body = response.json()
        assert response.status_code == 200
        assert [
            (
                item["traceId"],
                item["input"]["messages"][-1]["parts"][0]["text"],
                item["output"]["messages"][-1]["parts"][0]["text"],
                item["inputMissingReason"],
                item["outputMissingReason"],
            )
            for item in body["items"]
        ] == [
            ("trace-2", "Where is my parcel?", "Soon.", None, None),
            ("trace-1", "Where is my parcel?", "On its way.", None, None),
        ]

    def test_turns_side_missing_reason(self) -> None:
        events = TraceEvents(self.team)
        events.add(
            "trace-1",
            properties={
                **CHAT,
                "$ai_output_choices": [{"role": "assistant", "content": "x" * (TURN_SIDE_MAX_BYTES + 1)}],
            },
        )
        events.seed()

        response = post_turns(self, ["trace-1"])

        (item,) = response.json()["items"]
        assert (item["output"], item["outputMissingReason"], item["inputMissingReason"]) == (
            {"kind": "messages", "messages": []},
            "too_large",
            None,
        )

    def test_turns_normalizes_outside_query_slot(self) -> None:
        events = TraceEvents(self.team)
        events.add("trace-1", properties=CHAT)
        events.seed()

        with QuerySlotRecorder().recording("load_trace_turns") as recorder:
            response = post_turns(self, ["trace-1"])

        assert (response.status_code, recorder.loaded_while_holding, recorder.built_while_holding) == (
            200,
            [True],
            [False],
        )

    def test_turns_rejects_more_than_20_ids(self) -> None:
        response = post_turns(self, [f"trace-{n}" for n in range(TRACE_TURNS_MAX_IDS + 1)])

        assert response.status_code == 400
