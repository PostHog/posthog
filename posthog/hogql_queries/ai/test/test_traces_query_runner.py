from typing import Any, Literal, TypedDict

from posthog.hogql_queries.ai.traces_query_runner import TracesQueryRunner
from posthog.models import Team
from posthog.schema import TracesQuery
from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)


class InputMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class OutputMessage(TypedDict):
    role: Literal["user", "assistant", "tool"]
    content: str


def _calculate_tokens(messages: str | list[InputMessage] | list[OutputMessage]) -> int:
    if isinstance(messages, str):
        message = messages
    else:
        message = "".join([message["content"] for message in messages])
    return len(message)


def _create_ai_generation_event(
    input: str | list[InputMessage] | None = "What is the capital of Spain?",
    output: str | list[OutputMessage] | None = "Madrid",
    team: Team | None = None,
    distinct_id: str | None = None,
    trace_id: str | None = None,
    properties: dict[str, Any] | None = None,
):
    input_tokens = _calculate_tokens(input)
    output_tokens = _calculate_tokens(output)
    props = {
        "$ai_trace_id": trace_id,
        "$ai_latency": 1,
        "$ai_input_tokens": input_tokens,
        "$ai_output_tokens": output_tokens,
        "$ai_input_cost_usd": input_tokens,
        "$ai_output_cost_usd": output_tokens,
        "$ai_total_cost_usd": input_tokens + output_tokens,
    }
    if properties:
        props.update(properties)
    _create_event(
        event="$ai_generation",
        distinct_id=distinct_id,
        properties=props,
        team=team,
    )


class TestTracesQueryRunner(ClickhouseTestMixin, BaseTest):
    @snapshot_clickhouse_queries
    def test_traces_query_runner(self):
        _create_person(distinct_ids=["person1"], team=self.team)
        _create_person(distinct_ids=["person2"], team=self.team)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            input="Foo",
            output="Bar",
            team=self.team,
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            input="Foo",
            output="Bar",
            team=self.team,
        )
        _create_ai_generation_event(
            distinct_id="person2",
            trace_id="trace2",
            input="Foo",
            output="Bar",
            team=self.team,
        )

        results = TracesQueryRunner(team=self.team, query=TracesQuery()).calculate()
        self.assertEqual(len(results.results), 2)
