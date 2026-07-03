from datetime import datetime
from typing import Any
from uuid import uuid4

from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person

from parameterized import parameterized

from posthog.schema import DateRange, EventPropertyFilter, EventsQuery, PropertyOperator, TracesQuery

from posthog.hogql_queries.ai.traces_query_runner import TracesQueryRunner
from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.models.ai_events.test_util import bulk_create_ai_events


class TestHeavyAiPropertyFilters(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        _create_person(distinct_ids=["person1"], team=self.team)
        self.generation_uuids: dict[str, str] = {}
        # Mimic the ingestion split: the events-table copy has the heavy properties
        # stripped; the full content only exists on the ai_events table.
        self._create_generation(
            key="gen1",
            trace_id="trace1",
            timestamp=datetime(2024, 12, 1, 0, 5),
            output_content="the needle result",
        )
        self._create_generation(
            key="gen2",
            trace_id="trace2",
            timestamp=datetime(2024, 12, 1, 0, 10),
            output_content="plain result",
            extra_properties={"foo": "bar"},
        )
        self._create_generation(
            key="gen3",
            trace_id="trace3",
            timestamp=datetime(2024, 12, 1, 0, 15),
            output_content=None,
        )

    def _create_generation(
        self,
        *,
        key: str,
        trace_id: str,
        timestamp: datetime,
        output_content: str | None,
        extra_properties: dict[str, Any] | None = None,
    ) -> None:
        event_uuid = str(uuid4())
        self.generation_uuids[key] = event_uuid
        stripped_props: dict[str, Any] = {
            "$ai_trace_id": trace_id,
            "$ai_model": "gpt-4o",
            **(extra_properties or {}),
        }
        _create_event(
            event="$ai_generation",
            distinct_id="person1",
            team=self.team,
            timestamp=timestamp,
            event_uuid=event_uuid,
            properties=stripped_props,
        )
        ai_events_props = dict(stripped_props)
        if output_content is not None:
            ai_events_props["$ai_output_choices"] = [{"role": "assistant", "content": output_content}]
        bulk_create_ai_events(
            [
                {
                    "event": "$ai_generation",
                    "team": self.team,
                    "distinct_id": "person1",
                    "timestamp": timestamp,
                    "event_uuid": event_uuid,
                    "properties": ai_events_props,
                }
            ]
        )

    @parameterized.expand(
        [
            ("icontains", PropertyOperator.ICONTAINS, "needle", {"gen1"}),
            ("not_icontains", PropertyOperator.NOT_ICONTAINS, "needle", {"gen2"}),
            ("is_set", PropertyOperator.IS_SET, None, {"gen1", "gen2"}),
            ("is_not_set", PropertyOperator.IS_NOT_SET, None, {"gen3"}),
        ]
    )
    def test_events_query_filters_on_heavy_content(self, _name, operator, value, expected_keys):
        with freeze_time("2024-12-02T00:00:00Z"):
            response = EventsQueryRunner(
                team=self.team,
                query=EventsQuery(
                    kind="EventsQuery",
                    select=["uuid"],
                    event="$ai_generation",
                    after="-7d",
                    orderBy=["timestamp ASC"],
                    properties=[
                        EventPropertyFilter(key="$ai_output_choices", value=value, operator=operator, type="event")
                    ],
                ),
            ).calculate()

        self.assertEqual(
            {str(row[0]) for row in response.results},
            {self.generation_uuids[key] for key in expected_keys},
        )

    def test_traces_query_filters_on_heavy_content(self):
        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T01:00:00Z"),
                properties=[
                    EventPropertyFilter(
                        key="$ai_output_choices",
                        value="needle",
                        operator=PropertyOperator.ICONTAINS,
                        type="event",
                    )
                ],
            ),
        ).calculate()

        self.assertEqual([trace.id for trace in response.results], ["trace1"])

    def test_traces_query_combines_heavy_and_regular_filters(self):
        response = TracesQueryRunner(
            team=self.team,
            query=TracesQuery(
                dateRange=DateRange(date_from="2024-12-01T00:00:00Z", date_to="2024-12-01T01:00:00Z"),
                properties=[
                    EventPropertyFilter(
                        key="$ai_output_choices",
                        value="result",
                        operator=PropertyOperator.ICONTAINS,
                        type="event",
                    ),
                    EventPropertyFilter(key="foo", value="bar", operator=PropertyOperator.EXACT, type="event"),
                ],
            ),
        ).calculate()

        self.assertEqual([trace.id for trace in response.results], ["trace2"])
