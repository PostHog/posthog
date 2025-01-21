import uuid
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict
from uuid import UUID

from freezegun import freeze_time

from posthog.hogql_queries.ai.traces_query_runner import TracesQueryRunner
from posthog.models import PropertyDefinition, Team
from posthog.models.property_definition import PropertyType
from posthog.schema import (
    DateRange,
    EventPropertyFilter,
    LLMTrace,
    LLMTraceEvent,
    PersonPropertyFilter,
    PropertyOperator,
    TracesQuery,
)
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
                "inputTokens": 6.0,
                "outputTokens": 6.0,
                "inputCost": 6.0,
                "outputCost": 6.0,
                "totalCost": 12.0,
            },
        )
        self.assertEqual(trace.person.distinct_id, "person1")

        self.assertEqual(len(trace.events), 2)
        event = trace.events[0]
        self.assertIsNotNone(event.id)
        self.assertEventEqual(
            event,
            {
                "createdAt": datetime(2025, 1, 15, 0, tzinfo=UTC).isoformat(),
                "properties": {
                    "$ai_input": [{"role": "user", "content": "Foo"}],
                    "$ai_output_choices": [{"role": "assistant", "content": "Bar"}],
                    "$ai_latency": 1,
                    "$ai_input_tokens": 3,
                    "$ai_output_tokens": 3,
                    "$ai_input_cost_usd": 3,
                    "$ai_output_cost_usd": 3,
                    "$ai_total_cost_usd": 6,
                    "$ai_trace_id": "trace1",
                },
            },
        )

        event = trace.events[1]
        self.assertIsNotNone(event.id)
        self.assertEventEqual(
            event,
            {
                "createdAt": datetime(2025, 1, 15, 1, tzinfo=UTC).isoformat(),
                "properties": {
                    "$ai_input": [{"role": "user", "content": "Bar"}],
                    "$ai_output_choices": [{"role": "assistant", "content": "Baz"}],
                    "$ai_latency": 1,
                    "$ai_input_tokens": 3,
                    "$ai_output_tokens": 3,
                    "$ai_input_cost_usd": 3,
                    "$ai_output_cost_usd": 3,
                    "$ai_total_cost_usd": 6,
                    "$ai_trace_id": "trace1",
                },
            },
        )

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
        self.assertEqual(len(trace.events), 1)
        event = trace.events[0]
        self.assertIsNotNone(event.id)
        self.assertEventEqual(
            event,
            {
                "createdAt": datetime(2025, 1, 14, tzinfo=UTC).isoformat(),
                "properties": {
                    "$ai_input": [{"role": "user", "content": "Foo"}],
                    "$ai_output_choices": [{"role": "assistant", "content": "Bar"}],
                    "$ai_latency": 1,
                    "$ai_input_tokens": 3,
                    "$ai_output_tokens": 3,
                    "$ai_input_cost_usd": 3,
                    "$ai_output_cost_usd": 3,
                    "$ai_total_cost_usd": 6,
                    "$ai_trace_id": "trace2",
                },
            },
        )

    @freeze_time("2025-01-16T00:00:00Z")
    @snapshot_clickhouse_queries
    def test_trace_id_filter(self):
        _create_person(distinct_ids=["person1"], team=self.team)
        _create_person(distinct_ids=["person2"], team=self.team)
        _create_ai_generation_event(distinct_id="person1", trace_id="trace1", team=self.team)
        _create_ai_generation_event(distinct_id="person2", trace_id="trace2", team=self.team)

        response = TracesQueryRunner(team=self.team, query=TracesQuery(traceId="trace1")).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "trace1")

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
            },
        )

        response = TracesQueryRunner(team=self.team, query=TracesQuery()).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "trace1")
        self.assertEqual(response.results[0].totalLatency, 10.5)
        self.assertDictContainsSubset(
            {
                "$ai_latency": 10.5,
                "$ai_provider": "posthog",
                "$ai_model": "hog-destroyer",
                "$ai_http_status": 200,
                "$ai_base_url": "https://us.posthog.com",
            },
            response.results[0].events[0].properties,
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
            properties={"$ai_model_parameters": {"temperature": 0.5}},
        )

        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T00:10:00Z"),
            ),
        ).calculate()
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].id, "trace1")
        self.assertEqual(response.results[0].events[0].properties["$ai_model_parameters"], {"temperature": 0.5})
