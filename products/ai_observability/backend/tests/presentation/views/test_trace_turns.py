from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.ai_observability.backend.facade.api import TRACE_TURNS_MAX_IDS, TRACE_TURNS_MAX_SPAN
from products.ai_observability.backend.presentation.views.trace_page import TraceTurnsRequestSerializer

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
    def test_turns_answers_found_traces_in_request_order(self, _name: str, scopes: list[str] | None) -> None:
        events = TraceEvents(self.team)
        events.add("trace-1", properties=CHAT)
        events.add("trace-2", minutes=1, properties=CHAT)
        events.seed()

        response = post_turns(self, ["trace-2", "unknown", "trace-1"], scopes=scopes)

        assert (response.status_code, [item["traceId"] for item in response.json()["items"]]) == (
            200,
            ["trace-2", "trace-1"],
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

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    @patch(
        "products.ai_observability.backend.presentation.views.trace_page.ConversationReadBurstThrottle.rate",
        new="1/minute",
    )
    def test_throttles_a_browser_session_past_its_budget(self, _rate_limit: MagicMock) -> None:
        assert [post_turns(self, ["trace-1"]).status_code for _ in range(2)] == [200, 429]


@pytest.mark.parametrize(
    "span, valid",
    [(TRACE_TURNS_MAX_SPAN, True), (TRACE_TURNS_MAX_SPAN + timedelta(seconds=1), False)],
    ids=["at the cap", "past the cap"],
)
def test_a_turns_request_spans_at_most_the_capped_time(span: timedelta, valid: bool) -> None:
    serializer = TraceTurnsRequestSerializer(
        data={"trace_ids": ["trace-1"], "earliest_created_at": T0, "latest_created_at": T0 + span}
    )

    assert serializer.is_valid() is valid
