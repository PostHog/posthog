import uuid
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict
from uuid import UUID

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person, snapshot_clickhouse_queries

from posthog.schema import (
    DateRange,
    EventPropertyFilter,
    LLMTrace,
    LLMTraceEvent,
    PersonPropertyFilter,
    PropertyOperator,
    TracesQuery,
)

from posthog.hogql_queries.ai.traces_query_runner import TracesQueryRunner
from posthog.models import PropertyDefinition, Team
from posthog.models.property_definition import PropertyType


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
    *,
    input: str | list[InputMessage] = "Foo",
    output: str | list[OutputMessage] = "Bar",
    team: Team | None = None,
    distinct_id: str | None = None,
    trace_id: str | None = None,
    properties: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
    event_uuid: str | UUID | None = None,
):
    input_tokens = _calculate_tokens(input)
    output_tokens = _calculate_tokens(output)

    if isinstance(input, str):
        input_messages: list[InputMessage] = [{"role": "user", "content": input}]
    else:
        input_messages = input

    if isinstance(output, str):
        output_messages: list[OutputMessage] = [{"role": "assistant", "content": output}]
    else:
        output_messages = output

    props = {
        "$ai_trace_id": trace_id or str(uuid.uuid4()),
        "$ai_latency": 1,
        "$ai_input": input_messages,
        "$ai_output_choices": output_messages,
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
        timestamp=timestamp,
        event_uuid=str(event_uuid) if event_uuid else None,
    )


def _create_ai_trace_event(
    *,
    trace_id: str,
    trace_name: str | None,
    input_state: Any,
    output_state: Any,
    team: Team | None = None,
    distinct_id: str | None = None,
    properties: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
    event_uuid: str | UUID | None = None,
):
    props = {
        "$ai_trace_id": trace_id,
        "$ai_span_name": trace_name,
        "$ai_input_state": input_state,
        "$ai_output_state": output_state,
    }
    if properties:
        props.update(properties)

    _create_event(
        event="$ai_trace",
        distinct_id=distinct_id,
        properties=props,
        team=team,
        timestamp=timestamp,
        event_uuid=str(event_uuid) if event_uuid else None,
    )


def _create_ai_span_event(
    *,
    trace_id: str,
    input_state: Any,
    output_state: Any,
    span_id: str | None = None,
    parent_id: str | int | None = None,
    span_name: str | None = None,
    team: Team | None = None,
    distinct_id: str | None = None,
    properties: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
    event_uuid: str | UUID | None = None,
):
    props = {
        "$ai_trace_id": trace_id,
        "$ai_span_name": span_name,
        "$ai_input_state": input_state,
        "$ai_output_state": output_state,
        "$ai_span_id": span_id or str(uuid.uuid4()),
        "$ai_parent_id": parent_id or trace_id,
    }
    if properties:
        props.update(properties)

    _create_event(
        event="$ai_span",
        distinct_id=distinct_id,
        properties=props,
        team=team,
        timestamp=timestamp,
        event_uuid=str(event_uuid) if event_uuid else None,
    )


def _create_ai_embedding_event(
    *,
    input: str | list[InputMessage] = "Embed this text",
    team: Team | None = None,
    distinct_id: str | None = None,
    trace_id: str | None = None,
    properties: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
    event_uuid: str | UUID | None = None,
):
    input_tokens = _calculate_tokens(input)

    if isinstance(input, str):
        input_messages: list[InputMessage] = [{"role": "user", "content": input}]
    else:
        input_messages = input

    props = {
        "$ai_trace_id": trace_id or str(uuid.uuid4()),
        "$ai_latency": 0.5,
        "$ai_input": input_messages,
        "$ai_input_tokens": input_tokens,
        "$ai_input_cost_usd": input_tokens * 0.0001,
        "$ai_total_cost_usd": input_tokens * 0.0001,
        "$ai_model": "text-embedding-3-small",
        "$ai_provider": "openai",
    }
    if properties:
        props.update(properties)

    _create_event(
        event="$ai_embedding",
        distinct_id=distinct_id,
        properties=props,
        team=team,
        timestamp=timestamp,
        event_uuid=str(event_uuid) if event_uuid else None,
    )


class TestTracesQueryRunner(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self._create_properties()

    def _create_properties(self):
        numeric_props = {
            "$ai_latency",
            "$ai_input_tokens",
            "$ai_output_tokens",
            "$ai_input_cost_usd",
            "$ai_output_cost_usd",
            "$ai_total_cost_usd",
        }
        models_to_create = []
        for prop in numeric_props:
            prop_model = PropertyDefinition(
                team=self.team,
                name=prop,
                type=PropertyDefinition.Type.EVENT,
                property_type=PropertyType.Numeric,
            )
            models_to_create.append(prop_model)
        PropertyDefinition.objects.bulk_create(models_to_create)

    def assertTraceEqual(self, trace: LLMTrace, expected_trace: dict):
        trace_dict = trace.model_dump()
        for key, value in expected_trace.items():
            self.assertEqual(trace_dict[key], value, f"Field {key} does not match")

    def assertEventEqual(self, event: LLMTraceEvent, expected_event: dict):
        event_dict = event.model_dump()
        for key, value in expected_event.items():
            self.assertEqual(event_dict[key], value, f"Field {key} does not match")

    @freeze_time("2025-01-16T00:00:00Z")
    @snapshot_clickhouse_queries
    def test_field_mapping(self):
        _create_person(distinct_ids=["person1"], team=self.team)
        _create_person(distinct_ids=["person2"], team=self.team)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            input="Foo",
            output="Bar",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0),
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            input="Bar",
            output="Baz",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1),
        )
        _create_ai_generation_event(
            distinct_id="person2",
            trace_id="trace2",
            input="Foo",
            output="Bar",
            team=self.team,
            timestamp=datetime(2025, 1, 14),
        )

        response = TracesQueryRunner(team=self.team, query=TracesQuery()).calculate()
        self.assertEqual(len(response.results), 2)

        trace = response.results[0]
        self.assertTraceEqual(
            trace,
            {
                "id": "trace1",
                "createdAt": datetime(2025, 1, 15, 0, tzinfo=UTC).isoformat(),
                "totalLatency": 2.0,
                "inputState": None,
                "outputState": None,
                "inputTokens": 6.0,
                "outputTokens": 6.0,
                "inputCost": 6.0,
                "outputCost": 6.0,
                "totalCost": 12.0,
            },
        )
        self.assertEqual(trace.person.distinct_id, "person1")
        # Since these generation events don't have parent_id = trace_id, they are not root-level
        self.assertEqual(len(trace.events), 0)

        trace = response.results[1]
        self.assertTraceEqual(
            trace,
            {
                "id": "trace2",
                "createdAt": datetime(2025, 1, 14, tzinfo=UTC).isoformat(),
                "totalLatency": 1,
                "inputTokens": 3,
                "outputTokens": 3,
                "inputCost": 3,
                "outputCost": 3,
                "totalCost": 6,
            },
        )
        self.assertEqual(trace.person.distinct_id, "person2")
        # List view only returns summary events (metrics, feedback, and root-level events)
        # Since these generation events don't have parent_id = trace_id, they are not root-level
        self.assertEqual(len(trace.events), 0)

    # test_trace_id_filter removed - TracesQuery no longer supports traceId parameter

    @freeze_time("2025-01-16T00:00:00Z")
    @snapshot_clickhouse_queries
    def test_pagination(self):
        _create_person(distinct_ids=["person1"], team=self.team)
        _create_person(distinct_ids=["person2"], team=self.team)
        for i in range(11):
            _create_ai_generation_event(
                distinct_id="person1" if i % 2 == 0 else "person2",
                team=self.team,
                trace_id=f"trace_{i}",
                timestamp=datetime(2025, 1, 15, i),
            )
        response = TracesQueryRunner(team=self.team, query=TracesQuery(limit=4, offset=0)).calculate()
        self.assertEqual(response.hasMore, True)
        self.assertEqual(len(response.results), 5)
        self.assertEqual(response.results[0].id, "trace_10")
        self.assertEqual(response.results[1].id, "trace_9")
        self.assertEqual(response.results[2].id, "trace_8")
        self.assertEqual(response.results[3].id, "trace_7")
        self.assertEqual(response.results[4].id, "trace_6")

        response = TracesQueryRunner(team=self.team, query=TracesQuery(limit=4, offset=5)).calculate()
        self.assertEqual(response.hasMore, True)
        self.assertEqual(len(response.results), 5)
        self.assertEqual(response.results[0].id, "trace_5")
        self.assertEqual(response.results[1].id, "trace_4")
        self.assertEqual(response.results[2].id, "trace_3")
        self.assertEqual(response.results[3].id, "trace_2")
        self.assertEqual(response.results[4].id, "trace_1")

        response = TracesQueryRunner(team=self.team, query=TracesQuery(limit=4, offset=10)).calculate()
        self.assertEqual(response.hasMore, False)
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "trace_0")

    @freeze_time("2025-01-16T00:00:00Z")
    def test_maps_all_fields(self):
        _create_person(distinct_ids=["person1"], team=self.team)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
            properties={
                "$ai_latency": 10.5,
                "$ai_provider": "posthog",
                "$ai_model": "hog-destroyer",
                "$ai_http_status": 200,
                "$ai_base_url": "https://us.posthog.com",
                "$ai_parent_id": "trace1",
            },
        )

        response = TracesQueryRunner(team=self.team, query=TracesQuery()).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "trace1")
        self.assertEqual(response.results[0].totalLatency, 10.5)
        self.assertEqual(len(response.results[0].events), 1)
        self.assertLessEqual(
            {
                "$ai_latency": 10.5,
                "$ai_provider": "posthog",
                "$ai_model": "hog-destroyer",
                "$ai_http_status": 200,
                "$ai_base_url": "https://us.posthog.com",
                "$ai_parent_id": "trace1",
            }.items(),
            response.results[0].events[0].properties.items(),
        )

    @freeze_time("2025-01-01T00:00:00Z")
    def test_person_properties(self):
        _create_person(distinct_ids=["person1"], team=self.team, properties={"email": "test@posthog.com"})
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
        )
        response = TracesQueryRunner(team=self.team, query=TracesQuery()).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].person.created_at, "2025-01-01T00:00:00+00:00")
        self.assertEqual(response.results[0].person.properties, {"email": "test@posthog.com"})
        self.assertEqual(response.results[0].person.distinct_id, "person1")

    @freeze_time("2025-01-16T00:00:00Z")
    def test_date_range(self):
        _create_person(distinct_ids=["person1"], team=self.team)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
            timestamp=datetime(2025, 1, 15),
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace2",
            team=self.team,
            timestamp=datetime(2024, 12, 1),
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace3",
            team=self.team,
            timestamp=datetime(2024, 11, 1),
        )

        response = TracesQueryRunner(
            team=self.team, query=TracesQuery(dateRange=DateRange(date_from="-1m"))
        ).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "trace1")

        response = TracesQueryRunner(
            team=self.team, query=TracesQuery(dateRange=DateRange(date_from="-2m"))
        ).calculate()
        self.assertEqual(len(response.results), 2)
        self.assertEqual(response.results[0].id, "trace1")
        self.assertEqual(response.results[1].id, "trace2")

        response = TracesQueryRunner(
            team=self.team, query=TracesQuery(dateRange=DateRange(date_from="-3m", date_to="-2m"))
        ).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "trace3")

    def test_capture_range(self):
        _create_person(distinct_ids=["person1"], team=self.team)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 10),
        )

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z")),
        ).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "trace1")

        # Date is after the capture range
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace2",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 11),
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace2",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 12),
        )
        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z")),
        ).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "trace1")

        # Date is before the capture range
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace3",
            team=self.team,
            timestamp=datetime(2024, 11, 30, 23, 59),
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace3",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
        )
        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z")),
        ).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "trace1")

    def test_event_property_filters(self):
        _create_person(distinct_ids=["person1"], team=self.team)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace2",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 10),
            properties={"foo": "bar"},
        )

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z"),
                properties=[EventPropertyFilter(key="foo", value="bar", operator=PropertyOperator.EXACT)],
            ),
        ).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "trace2")

    def test_person_property_filters(self):
        _create_person(distinct_ids=["person1"], team=self.team, properties={"foo": "bar"})
        _create_person(distinct_ids=["person2"], team=self.team, properties={"foo": "baz"})
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
        )
        _create_ai_generation_event(
            distinct_id="person2",
            trace_id="trace2",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 10),
        )

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z"),
                properties=[PersonPropertyFilter(key="foo", value="bar", operator=PropertyOperator.EXACT)],
            ),
        ).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "trace1")

    def test_model_parameters(self):
        _create_person(distinct_ids=["person1"], team=self.team, properties={"foo": "bar"})
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
            properties={
                "$ai_model_parameters": {"temperature": 0.5},
                "$ai_parent_id": "trace1",
            },
        )

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z"),
            ),
        ).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "trace1")
        self.assertEqual(len(response.results[0].events), 1)
        self.assertEqual(response.results[0].events[0].properties["$ai_model_parameters"], {"temperature": 0.5})

    @snapshot_clickhouse_queries
    def test_properties_filter_with_multiple_events_in_group(self):
        _create_person(distinct_ids=["person1"], team=self.team)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
            properties={"foo": "bar"},
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
            properties={"foo": "baz"},
        )

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                properties=[EventPropertyFilter(key="foo", value="bar", operator=PropertyOperator.EXACT)],
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z"),
            ),
        ).calculate()
        self.assertEqual(len(response.results), 1)

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                properties=[EventPropertyFilter(key="foo", value="baz", operator=PropertyOperator.EXACT)],
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z"),
            ),
        ).calculate()
        self.assertEqual(len(response.results), 1)

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                properties=[EventPropertyFilter(key="foo", value="barz", operator=PropertyOperator.EXACT)],
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z"),
            ),
        ).calculate()
        self.assertEqual(len(response.results), 0)

    @snapshot_clickhouse_queries
    def test_trace_property_filter_for_event_group(self):
        _create_person(distinct_ids=["person1"], team=self.team)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 2),
            properties={"foo": "bar"},
        )
        _create_ai_trace_event(
            trace_id="trace1",
            trace_name="runnable",
            input_state={"messages": [{"role": "user", "content": "Foo"}]},
            output_state={"messages": [{"role": "user", "content": "Foo"}, {"role": "assistant", "content": "Bar"}]},
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 5),
        )

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                properties=[
                    EventPropertyFilter(key="$ai_span_name", value="runnable", operator=PropertyOperator.EXACT)
                ],
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z"),
            ),
        ).calculate()
        self.assertEqual(len(response.results), 1)

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                properties=[EventPropertyFilter(key="foo", value="bar", operator=PropertyOperator.EXACT)],
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z"),
            ),
        ).calculate()
        self.assertEqual(len(response.results), 1)

        # Shouldn't return anything because there isn't such trace
        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                properties=[
                    EventPropertyFilter(key="$ai_span_name", value="runnable", operator=PropertyOperator.EXACT),
                    EventPropertyFilter(key="foo", value="bar", operator=PropertyOperator.EXACT),
                ],
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z"),
            ),
        ).calculate()
        self.assertEqual(len(response.results), 0)

    def test_trace_name_fallback(self):
        """
        $ai_trace_name is a deprecated property, but we still want to support it for backwards compatibility.
        """
        _create_person(distinct_ids=["person1"], team=self.team)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
        )
        _create_ai_trace_event(
            trace_id="trace1",
            trace_name="runnable",
            input_state={"messages": [{"role": "user", "content": "Foo"}]},
            output_state={"messages": [{"role": "user", "content": "Foo"}, {"role": "assistant", "content": "Bar"}]},
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 5),
        )

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z"),
            ),
        ).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].traceName, "runnable")

        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace2",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
        )
        _create_ai_trace_event(
            trace_id="trace2",
            trace_name=None,
            input_state={"messages": [{"role": "user", "content": "Foo"}]},
            output_state={"messages": [{"role": "user", "content": "Foo"}, {"role": "assistant", "content": "Bar"}]},
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 5),
            properties={"$ai_trace_name": "bar"},
        )
        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z"),
            ),
        ).calculate()
        self.assertEqual(len(response.results), 2)  # Should return both traces
        # Find trace2 in the results
        trace2 = next((r for r in response.results if r.id == "trace2"), None)
        assert trace2 is not None
        self.assertEqual(trace2.traceName, "bar")

    def test_returns_metrics_and_feedback_events(self):
        _create_person(distinct_ids=["person1"], team=self.team)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
        )
        _create_event(
            distinct_id="person1",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 1),
            event="$ai_metric",
            properties={
                "$ai_trace_id": "trace1",
            },
        )
        _create_event(
            distinct_id="person1",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 2),
            event="$ai_feedback",
            properties={
                "$ai_trace_id": "trace1",
            },
        )

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z"),
            ),
        ).calculate()
        self.assertEqual(len(response.results), 1)
        # List view only returns metrics, feedback, and root-level events
        # The generation event is not root-level (no parent_id = trace_id)
        self.assertEqual(len(response.results[0].events), 2)
        self.assertEqual(response.results[0].events[0].event, "$ai_metric")
        self.assertEqual(response.results[0].events[1].event, "$ai_feedback")

    def test_aggregates_full_trace_events_with_property_filters(self):
        trace_id = str(uuid.uuid4())

        _create_person(distinct_ids=["person1"], team=self.team)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
            properties={
                "$ai_input_tokens": 1,
                "hay": "needle",
            },
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 1),
            properties={
                "$ai_input_tokens": 1,
            },
        )
        _create_ai_trace_event(
            trace_id=trace_id,
            input_state={},
            output_state={},
            trace_name="runnable",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 3),
            distinct_id="person1",
        )

        # Should return total latency of 2
        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z"),
            ),
        ).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].inputTokens, 2)

        # With a property filter, should also return total latency of 2
        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z"),
                properties=[EventPropertyFilter(key="hay", value="needle", operator=PropertyOperator.EXACT)],
            ),
        ).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].inputTokens, 2)

    def test_removes_duplicate_events(self):
        """ClickHouse might sometimes return unmerged (duplicate) events."""
        trace_id = str(uuid.uuid4())
        event_id = str(uuid.uuid4())

        _create_person(distinct_ids=["person1"], team=self.team)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
            event_uuid=event_id,
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
            event_uuid=event_id,
        )
        _create_ai_trace_event(
            trace_id=trace_id,
            input_state={},
            output_state={},
            trace_name="runnable",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 3),
            distinct_id="person1",
        )

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z"),
            ),
        ).calculate()
        self.assertEqual(len(response.results), 1)
        # Generation events without parent_id = trace_id are not root-level, so not included
        self.assertEqual(len(response.results[0].events), 0)

    def test_trace_name_from_trace_event(self):
        """Test that trace_name comes from $ai_trace events when they exist."""
        _create_person(distinct_ids=["person1"], team=self.team)
        trace_id = "trace_with_trace_event"

        # Create a generation event with trace_name in properties first
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
            properties={"$ai_trace_name": "from_generation_event"},
        )

        # Create a trace event with trace_name that should override
        _create_ai_trace_event(
            trace_id=trace_id,
            trace_name="from_trace_event",
            input_state={},
            output_state={},
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 1),
            distinct_id="person1",
        )

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z"),
            ),
        ).calculate()

        self.assertEqual(len(response.results), 1)
        # Should use trace_name from trace event
        self.assertEqual(response.results[0].traceName, "from_trace_event")

    def test_trace_name_fallback_when_no_trace_events(self):
        """Test that trace_name falls back to generation events when no $ai_trace events exist."""
        _create_person(distinct_ids=["person1"], team=self.team)
        trace_id = "trace_without_trace_events"

        # Create only generation events with trace_name in properties
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
            properties={"$ai_trace_name": "fallback_trace_name"},
        )

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z"),
            ),
        ).calculate()

        self.assertEqual(len(response.results), 1)
        # Should fall back to trace_name from generation events
        self.assertEqual(response.results[0].traceName, "fallback_trace_name")

    def test_trace_name_when_no_names_exist(self):
        """Test that trace_name is None when no names exist in either trace or generation events."""
        _create_person(distinct_ids=["person1"], team=self.team)
        trace_id = "trace_without_names"

        # Create generation events with no trace_name or span_name
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
        )

        # Create a trace event with no trace_name
        _create_ai_trace_event(
            trace_id=trace_id,
            trace_name=None,
            input_state={},
            output_state={},
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 1),
            distinct_id="person1",
        )

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z"),
            ),
        ).calculate()

        self.assertEqual(len(response.results), 1)
        # Should be None when no names exist
        self.assertIsNone(response.results[0].traceName)

    def test_trace_name_with_only_generation_events(self):
        """Test that trace_name works when only generation events exist (no trace events at all)."""
        _create_person(distinct_ids=["person1"], team=self.team)
        trace_id = "trace_only_generation"

        # Create only generation events with no trace events
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
        )

        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 1),
        )

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z"),
            ),
        ).calculate()

        self.assertEqual(len(response.results), 1)
        # Should be None when no names exist in any events
        self.assertIsNone(response.results[0].traceName)

    def test_mixed_type_parent_trace_comparison(self):
        """Test that parent_id and trace_id comparison works with mixed types (string vs float)."""
        _create_person(distinct_ids=["person1"], team=self.team)
        trace_id = "12345"  # String trace ID

        # Create a span with numeric parent_id that equals trace_id
        _create_ai_span_event(
            trace_id=trace_id,
            span_id="span1",
            parent_id=12345,  # Numeric parent_id
            span_name="root_span",
            input_state={},
            output_state={},
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
            distinct_id="person1",
            properties={
                "$ai_latency": 5.0,
                "$ai_parent_id": 12345,  # Ensure it's stored as number
            },
        )

        # Create another span with string parent_id
        _create_ai_span_event(
            trace_id=trace_id,
            span_id="span2",
            parent_id="12345",  # String parent_id matching trace_id
            span_name="child_span",
            input_state={},
            output_state={},
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 1),
            distinct_id="person1",
            properties={
                "$ai_latency": 3.0,
                "$ai_parent_id": "12345",  # Ensure it's stored as string
            },
        )

        # Create a generation event with trace_id as parent
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 2),
            properties={
                "$ai_latency": 2.0,
                "$ai_parent_id": trace_id,  # Parent is the trace itself
            },
        )

        # Query should work despite type mismatches
        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T01:00:00Z"),
            ),
        ).calculate()

        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, trace_id)

        # Total latency should count all root-level items (where parent_id = trace_id)
        # With toString() fix: span1 (5.0) + span2 (3.0) + generation (2.0) = 10.0
        # All three have parent_id that equals trace_id when converted to string
        self.assertEqual(response.results[0].totalLatency, 10.0)

        # Query for full trace details
        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T01:00:00Z"),
            ),
        ).calculate()

        self.assertEqual(len(response.results), 1)
        # Should have all 3 events in the full trace
        self.assertEqual(len(response.results[0].events), 3)

    def test_latency_missing_intermediate_levels(self):
        """
        Test that latency is calculated from grandchildren when intermediate levels lack latency.

        Tree structure:
        Trace "trace_missing_intermediate" (no latency)
        ├── Span A ($ai_span_id="span_a", no latency)
        │   ├── Generation A1 ($ai_parent_id="span_a", 100ms)
        │   └── Generation A2 ($ai_parent_id="span_a", 150ms)
        └── Span B ($ai_span_id="span_b", no latency)
            └── Generation B1 ($ai_parent_id="span_b", 200ms)

        Expected: 450ms (sum of all generations)
        """
        _create_person(distinct_ids=["person1"], team=self.team)
        trace_id = "trace_missing_intermediate"

        # Create spans with no latency, using realistic span_id structure
        _create_ai_span_event(
            trace_id=trace_id,
            span_name="span_a",
            input_state={},
            output_state={},
            team=self.team,
            distinct_id="person1",
            timestamp=datetime(2024, 12, 1, 0, 0),
            properties={"$ai_span_id": "span_a", "$ai_parent_id": trace_id},
            # No $ai_latency property
        )
        _create_ai_span_event(
            trace_id=trace_id,
            span_name="span_b",
            input_state={},
            output_state={},
            team=self.team,
            distinct_id="person1",
            timestamp=datetime(2024, 12, 1, 0, 1),
            properties={"$ai_span_id": "span_b", "$ai_parent_id": trace_id},
            # No $ai_latency property
        )

        # Create generations with latency as children of spans (no span_id = automatic leaves)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 2),
            properties={"$ai_latency": 100, "$ai_parent_id": "span_a"},
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 3),
            properties={"$ai_latency": 150, "$ai_parent_id": "span_a"},
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 4),
            properties={"$ai_latency": 200, "$ai_parent_id": "span_b"},
        )

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T01:00:00Z")),
        ).calculate()

        self.assertEqual(len(response.results), 1)
        # Should sum all generation latencies: 100 + 150 + 200 = 450
        self.assertEqual(response.results[0].totalLatency, 450.0)

    @pytest.mark.skip(
        reason="This case is currently broken as is. Implementing a fix would require figuring out efficient trace tree traversal."
    )
    def test_latency_inconsistent_hierarchy_levels(self):
        """
        Test latency calculation with mixed levels having latency data.

        Tree structure:
        Trace "trace_inconsistent" (no latency)
        ├── Span A ($ai_span_id="span_a", 250ms)
        └── Span B ($ai_span_id="span_b", no latency)
            └── Generation B1 ($ai_parent_id="span_b", 200ms)

        Expected: 450ms (Span A + Generation B1)
        """
        _create_person(distinct_ids=["person1"], team=self.team)
        trace_id = "trace_inconsistent"

        # Span A has latency and is direct child of trace
        _create_ai_span_event(
            trace_id=trace_id,
            span_name="span_a",
            input_state={},
            output_state={},
            team=self.team,
            distinct_id="person1",
            timestamp=datetime(2024, 12, 1, 0, 0),
            properties={"$ai_span_id": "span_a", "$ai_parent_id": trace_id, "$ai_latency": 250},
        )

        # Span B has no latency
        _create_ai_span_event(
            trace_id=trace_id,
            span_name="span_b",
            input_state={},
            output_state={},
            team=self.team,
            distinct_id="person1",
            timestamp=datetime(2024, 12, 1, 0, 1),
            properties={"$ai_span_id": "span_b", "$ai_parent_id": trace_id},
            # No $ai_latency property
        )

        # Generation B1 is grandchild with latency (no span_id = automatic leaf)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 2),
            properties={"$ai_latency": 200, "$ai_parent_id": "span_b"},
        )

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T01:00:00Z")),
        ).calculate()

        self.assertEqual(len(response.results), 1)
        # Should sum: Span A (250) + Generation B1 (200) = 450
        self.assertEqual(response.results[0].totalLatency, 450.0)

    def test_latency_no_double_counting_when_parent_has_latency(self):
        """
        Test that we don't double count when parent latency equals sum of children.

        Tree structure:
        Trace "trace_double_count" (no latency)
        ├── Span A ($ai_span_id="span_a", 250ms = sum of children)
        │   ├── Generation A1 ($ai_parent_id="span_a", 100ms)
        │   └── Generation A2 ($ai_parent_id="span_a", 150ms)
        └── Generation B ($ai_parent_id=trace_id, 200ms, direct child)

        Expected: 450ms (Span A + Generation B, no double counting)
        """
        _create_person(distinct_ids=["person1"], team=self.team)
        trace_id = "trace_double_count"

        # Span A has latency equal to sum of its children
        _create_ai_span_event(
            trace_id=trace_id,
            span_name="span_a",
            input_state={},
            output_state={},
            team=self.team,
            distinct_id="person1",
            timestamp=datetime(2024, 12, 1, 0, 0),
            properties={"$ai_span_id": "span_a", "$ai_parent_id": trace_id, "$ai_latency": 250},
        )

        # Children of Span A (no span_id = automatic leaves, but should be excluded due to parent having latency)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 1),
            properties={"$ai_latency": 100, "$ai_parent_id": "span_a"},
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 2),
            properties={"$ai_latency": 150, "$ai_parent_id": "span_a"},
        )

        # Direct child of trace (should be counted, no span_id = automatic leaf)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 3),
            properties={"$ai_latency": 200, "$ai_parent_id": trace_id},
        )

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T01:00:00Z")),
        ).calculate()

        self.assertEqual(len(response.results), 1)
        # Should count: Span A (250) + Direct Generation (200) = 450
        # Should NOT double-count the children of Span A
        self.assertEqual(response.results[0].totalLatency, 450.0)

    def test_latency_no_span_id_automatic_leaves(self):
        """
        Test events without $ai_span_id are automatic leaves.

        Tree structure:
        Trace "trace_no_span_id" (no latency)
        ├── Generation A (no $ai_span_id, $ai_parent_id=trace_id, 100ms)
        ├── Generation B (no $ai_span_id, $ai_parent_id=trace_id, 150ms)
        └── Generation C (no $ai_span_id, no $ai_parent_id, 200ms)

        Expected: 450ms (all are leaves, all counted)
        """
        _create_person(distinct_ids=["person1"], team=self.team)
        trace_id = "trace_no_span_id"

        # Generation A: no span_id, parent_id=trace_id, has latency (automatic leaf)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
            properties={"$ai_latency": 100, "$ai_parent_id": trace_id},
            # No $ai_span_id = automatic leaf
        )

        # Generation B: no span_id, parent_id=trace_id, has latency (automatic leaf)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 1),
            properties={"$ai_latency": 150, "$ai_parent_id": trace_id},
            # No $ai_span_id = automatic leaf
        )

        # Generation C: no span_id, no parent_id, has latency (root leaf)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 2),
            properties={"$ai_latency": 200},
            # No $ai_span_id = automatic leaf, no $ai_parent_id = root child
        )

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T01:00:00Z")),
        ).calculate()

        self.assertEqual(len(response.results), 1)
        # Should sum all generation latencies: 100 + 150 + 200 = 450
        self.assertEqual(response.results[0].totalLatency, 450.0)

    def test_latency_no_parent_id_root_leaves(self):
        """
        Test events with no $ai_parent_id become root children.

        Tree structure:
        Trace "trace_no_parent_id" (no latency)
        ├── Generation A ($ai_span_id="gen_a", no $ai_parent_id, 100ms)
        └── Generation B ($ai_span_id="gen_b", no $ai_parent_id, 150ms)

        Expected: 250ms (both are root children)
        """
        _create_person(distinct_ids=["person1"], team=self.team)
        trace_id = "trace_no_parent_id"

        # Generation A: has span_id, no parent_id, has latency (root child)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
            properties={"$ai_span_id": "gen_a", "$ai_latency": 100},
            # No $ai_parent_id = root child
        )

        # Generation B: has span_id, no parent_id, has latency (root child)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 1),
            properties={"$ai_span_id": "gen_b", "$ai_latency": 150},
            # No $ai_parent_id = root child
        )

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T01:00:00Z")),
        ).calculate()

        self.assertEqual(len(response.results), 1)
        # Should sum both root children: 100 + 150 = 250
        self.assertEqual(response.results[0].totalLatency, 250.0)

    def test_latency_mixed_span_id_presence(self):
        """
        Test mixed presence of $ai_span_id in hierarchy.

        Tree structure:
        Trace "trace_mixed_span_id" (no latency)
        ├── Span A ($ai_span_id="span_a", 100ms)
        │   └── Generation A1 (no $ai_span_id, $ai_parent_id="span_a", 50ms)
        └── Generation B (no $ai_span_id, $ai_parent_id=trace_id, 200ms)

        Expected: 300ms (Span A 100ms + Generation B 200ms, exclude A1)
        """
        _create_person(distinct_ids=["person1"], team=self.team)
        trace_id = "trace_mixed_span_id"

        # Span A: has span_id and latency (can be referenced by children)
        _create_ai_span_event(
            trace_id=trace_id,
            span_name="span_a",
            input_state={},
            output_state={},
            team=self.team,
            distinct_id="person1",
            timestamp=datetime(2024, 12, 1, 0, 0),
            properties={"$ai_span_id": "span_a", "$ai_parent_id": trace_id, "$ai_latency": 100},
        )

        # Generation A1: no span_id (leaf), parent="span_a" which has latency (should be excluded)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 1),
            properties={"$ai_latency": 50, "$ai_parent_id": "span_a"},
            # No $ai_span_id = automatic leaf, but parent has latency so excluded
        )

        # Generation B: no span_id (leaf), parent=trace_id (root leaf, should be included)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id=trace_id,
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 2),
            properties={"$ai_latency": 200, "$ai_parent_id": trace_id},
            # No $ai_span_id = automatic leaf, root child so included
        )

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T01:00:00Z")),
        ).calculate()

        self.assertEqual(len(response.results), 1)
        # Should sum: Span A (100) + Generation B (200) = 300, exclude Generation A1
        self.assertEqual(response.results[0].totalLatency, 300.0)

    @freeze_time("2025-01-16T00:00:00Z")
    def test_person_id_filter(self):
        """Test that personId parameter filters traces by person."""
        person1 = _create_person(distinct_ids=["user1"], team=self.team)
        person2 = _create_person(distinct_ids=["user2"], team=self.team)

        _create_ai_generation_event(
            distinct_id="user1",
            trace_id="trace1",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 0),
        )

        _create_ai_generation_event(
            distinct_id="user2",
            trace_id="trace2",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1, 0),
        )

        response = TracesQueryRunner(team=self.team, query=TracesQuery()).calculate()
        self.assertEqual(len(response.results), 2)

        response = TracesQueryRunner(team=self.team, query=TracesQuery(personId=str(person1.uuid))).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "trace1")
        self.assertEqual(response.results[0].person.uuid, str(person1.uuid))

        response = TracesQueryRunner(team=self.team, query=TracesQuery(personId=str(person2.uuid))).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "trace2")
        self.assertEqual(response.results[0].person.uuid, str(person2.uuid))

        response = TracesQueryRunner(team=self.team, query=TracesQuery(personId=str(uuid.uuid4()))).calculate()
        self.assertEqual(len(response.results), 0)

    def test_embedding_only_trace_cost_aggregation(self):
        """Test that embedding-only traces properly aggregate costs in list view (regression test)."""
        _create_person(distinct_ids=["person1"], team=self.team)
        trace_id = "embedding_only_trace"

        # Create multiple embedding events with costs
        _create_ai_embedding_event(
            distinct_id="person1",
            trace_id=trace_id,
            input="First text to embed",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 0),
        )
        _create_ai_embedding_event(
            distinct_id="person1",
            trace_id=trace_id,
            input="Second text to embed",
            team=self.team,
            timestamp=datetime(2024, 12, 1, 0, 1),
        )

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T01:00:00Z")),
        ).calculate()

        self.assertEqual(len(response.results), 1)
        trace = response.results[0]

        # Verify costs are aggregated (not null)
        # "First text to embed" = 19 chars, "Second text to embed" = 20 chars
        expected_input_cost = 0.0039
        self.assertIsNotNone(trace.inputCost)
        self.assertEqual(trace.inputCost, expected_input_cost)
        self.assertEqual(trace.totalCost, expected_input_cost)

        # Embeddings typically don't set output cost/tokens, so they'll be None
        self.assertIsNone(trace.outputCost)
        self.assertIsNone(trace.outputTokens)

        # Verify input tokens are aggregated
        expected_input_tokens = 39
        self.assertIsNotNone(trace.inputTokens)
        self.assertEqual(trace.inputTokens, expected_input_tokens)
