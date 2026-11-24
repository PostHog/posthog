from datetime import timedelta

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.test.persons import create_person

from .trace_fixtures import PAGE_BOUNDS, T0, TraceEvents, post_page_read


@time_machine.travel(T0 + timedelta(days=1), tick=False)
class TestTracePeopleViewSet(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand([("browser session", None), ("read key", ["llm_analytics:read"])])
    def test_labels_each_trace_on_a_page_by_its_person(self, _name: str, scopes: list[str] | None) -> None:
        create_person(team=self.team, distinct_ids=["ada-id"], properties={"email": "ada@example.com"})
        events = TraceEvents(self.team)
        events.add("trace-1", distinct_id="ada-id")
        events.seed()

        response = post_page_read(self, "people", {"trace_ids": ["trace-1"], **PAGE_BOUNDS}, scopes=scopes)

        assert (response.status_code, response.json()) == (
            200,
            {"items": [{"traceId": "trace-1", "person": {"distinctId": "ada-id", "label": "ada@example.com"}}]},
        )
