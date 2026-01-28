import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person

from posthog.schema import DateRange, EventPropertyFilter, PropertyOperator, TraceNeighborsQuery

from posthog.hogql_queries.ai.trace_neighbors_query_runner import TraceNeighborsQueryRunner


def _create_ai_generation_event(
    *,
    team=None,
    distinct_id: str | None = None,
    trace_id: str | None = None,
    properties: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
):
    props = {
        "$ai_trace_id": trace_id or str(uuid.uuid4()),
        "$ai_latency": 1,
        "$ai_input_tokens": 10,
        "$ai_output_tokens": 10,
    }
    if properties:
        props.update(properties)

    _create_event(
        event="$ai_generation",
        distinct_id=distinct_id,
        properties=props,
        team=team,
        timestamp=timestamp,
    )


class TestTraceNeighborsQueryRunner(ClickhouseTestMixin, BaseTest):
    def test_finds_prev_and_next_traces(self):
        """Test that the query finds both previous and next traces correctly."""
        _create_person(distinct_ids=["person1"], team=self.team)

        # Create traces at different times
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 0, tzinfo=UTC),
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace2",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1, 0, tzinfo=UTC),
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace3",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 2, 0, tzinfo=UTC),
        )

        # Query from trace2 (middle trace)
        response = TraceNeighborsQueryRunner(
            team=self.team,
            query=TraceNeighborsQuery(
                traceId="trace2",
                timestamp=datetime(2025, 1, 15, 1, 0, tzinfo=UTC).isoformat(),
            ),
        ).calculate()

        self.assertEqual(response.olderTraceId, "trace1")
        self.assertEqual(response.olderTimestamp, datetime(2025, 1, 15, 0, 0, tzinfo=UTC).isoformat())
        self.assertEqual(response.newerTraceId, "trace3")
        self.assertEqual(response.newerTimestamp, datetime(2025, 1, 15, 2, 0, tzinfo=UTC).isoformat())

    def test_no_prev_trace_when_first(self):
        """Test that no previous trace is returned when current trace is first."""
        _create_person(distinct_ids=["person1"], team=self.team)

        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 0, tzinfo=UTC),
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace2",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1, 0, tzinfo=UTC),
        )

        # Query from trace1 (first trace)
        response = TraceNeighborsQueryRunner(
            team=self.team,
            query=TraceNeighborsQuery(
                traceId="trace1",
                timestamp=datetime(2025, 1, 15, 0, 0, tzinfo=UTC).isoformat(),
            ),
        ).calculate()

        self.assertIsNone(response.olderTraceId)
        self.assertIsNone(response.olderTimestamp)
        self.assertEqual(response.newerTraceId, "trace2")
        self.assertEqual(response.newerTimestamp, datetime(2025, 1, 15, 1, 0, tzinfo=UTC).isoformat())

    def test_no_next_trace_when_last(self):
        """Test that no next trace is returned when current trace is last."""
        _create_person(distinct_ids=["person1"], team=self.team)

        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 0, tzinfo=UTC),
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace2",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1, 0, tzinfo=UTC),
        )

        # Query from trace2 (last trace)
        response = TraceNeighborsQueryRunner(
            team=self.team,
            query=TraceNeighborsQuery(
                traceId="trace2",
                timestamp=datetime(2025, 1, 15, 1, 0, tzinfo=UTC).isoformat(),
            ),
        ).calculate()

        self.assertEqual(response.olderTraceId, "trace1")
        self.assertEqual(response.olderTimestamp, datetime(2025, 1, 15, 0, 0, tzinfo=UTC).isoformat())
        self.assertIsNone(response.newerTraceId)
        self.assertIsNone(response.newerTimestamp)

    def test_identical_timestamps_deterministic_ordering(self):
        """Test that traces with identical timestamps are ordered deterministically by trace_id."""
        _create_person(distinct_ids=["person1"], team=self.team)

        same_timestamp = datetime(2025, 1, 15, 0, 0, tzinfo=UTC)

        # Create traces with identical timestamps but different IDs
        # The ordering should be: trace_a < trace_b < trace_c
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace_a",
            team=self.team,
            timestamp=same_timestamp,
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace_b",
            team=self.team,
            timestamp=same_timestamp,
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace_c",
            team=self.team,
            timestamp=same_timestamp,
        )

        # Query from trace_b (middle)
        response = TraceNeighborsQueryRunner(
            team=self.team,
            query=TraceNeighborsQuery(
                traceId="trace_b",
                timestamp=same_timestamp.isoformat(),
            ),
        ).calculate()

        self.assertEqual(response.olderTraceId, "trace_a")
        self.assertEqual(response.newerTraceId, "trace_c")

        # Query from trace_a (first)
        response = TraceNeighborsQueryRunner(
            team=self.team,
            query=TraceNeighborsQuery(
                traceId="trace_a",
                timestamp=same_timestamp.isoformat(),
            ),
        ).calculate()

        self.assertIsNone(response.olderTraceId)
        self.assertEqual(response.newerTraceId, "trace_b")

        # Query from trace_c (last)
        response = TraceNeighborsQueryRunner(
            team=self.team,
            query=TraceNeighborsQuery(
                traceId="trace_c",
                timestamp=same_timestamp.isoformat(),
            ),
        ).calculate()

        self.assertEqual(response.olderTraceId, "trace_b")
        self.assertIsNone(response.newerTraceId)

    def test_uses_max_timestamp_per_trace(self):
        """Test that the query uses max timestamp per trace when trace has multiple events."""
        _create_person(distinct_ids=["person1"], team=self.team)

        # trace1: single event at 00:00
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 0, tzinfo=UTC),
        )

        # trace2: multiple events, max at 01:30
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace2",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1, 0, tzinfo=UTC),
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace2",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1, 30, tzinfo=UTC),
        )

        # trace3: single event at 02:00
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace3",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 2, 0, tzinfo=UTC),
        )

        # Query from trace2 using its max timestamp
        response = TraceNeighborsQueryRunner(
            team=self.team,
            query=TraceNeighborsQuery(
                traceId="trace2",
                timestamp=datetime(2025, 1, 15, 1, 30, tzinfo=UTC).isoformat(),
            ),
        ).calculate()

        self.assertEqual(response.olderTraceId, "trace1")
        self.assertEqual(response.newerTraceId, "trace3")

    def test_respects_date_range_filter(self):
        """Test that explicit date range is respected."""
        _create_person(distinct_ids=["person1"], team=self.team)

        # Create traces spanning a wide range
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace_old",
            team=self.team,
            timestamp=datetime(2025, 1, 1, 0, 0, tzinfo=UTC),
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace_middle",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 0, tzinfo=UTC),
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace_recent",
            team=self.team,
            timestamp=datetime(2025, 1, 20, 0, 0, tzinfo=UTC),
        )

        # Query with date range that excludes trace_old
        response = TraceNeighborsQueryRunner(
            team=self.team,
            query=TraceNeighborsQuery(
                traceId="trace_middle",
                timestamp=datetime(2025, 1, 15, 0, 0, tzinfo=UTC).isoformat(),
                dateRange=DateRange(
                    date_from="2025-01-10T00:00:00Z",
                    date_to="2025-01-25T00:00:00Z",
                ),
            ),
        ).calculate()

        # Should not find trace_old since it's outside date range
        self.assertIsNone(response.olderTraceId)
        self.assertEqual(response.newerTraceId, "trace_recent")

    def test_default_date_range_window(self):
        """Test that default date range is ±3 days around trace timestamp."""
        _create_person(distinct_ids=["person1"], team=self.team)

        current_time = datetime(2025, 1, 15, 0, 0, tzinfo=UTC)

        # Create traces outside the 3-day window (should not be found)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace_too_old",
            team=self.team,
            timestamp=current_time - timedelta(days=4),
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace_too_new",
            team=self.team,
            timestamp=current_time + timedelta(days=4),
        )

        # Create traces within the 3-day window (should be found)
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace_prev",
            team=self.team,
            timestamp=current_time - timedelta(days=2),
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace_current",
            team=self.team,
            timestamp=current_time,
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace_next",
            team=self.team,
            timestamp=current_time + timedelta(days=2),
        )

        # Query without explicit date range
        response = TraceNeighborsQueryRunner(
            team=self.team,
            query=TraceNeighborsQuery(
                traceId="trace_current",
                timestamp=current_time.isoformat(),
            ),
        ).calculate()

        # Should find neighbors within 3-day window
        self.assertEqual(response.olderTraceId, "trace_prev")
        self.assertEqual(response.newerTraceId, "trace_next")

    def test_property_filters(self):
        """Test that property filters are applied correctly."""
        _create_person(distinct_ids=["person1"], team=self.team)

        # Create traces with different properties
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 0, tzinfo=UTC),
            properties={"env": "prod"},
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace2",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1, 0, tzinfo=UTC),
            properties={"env": "prod"},
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace3_dev",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1, 30, tzinfo=UTC),
            properties={"env": "dev"},
        )
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace4",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 2, 0, tzinfo=UTC),
            properties={"env": "prod"},
        )

        # Query from trace2 with property filter for prod
        response = TraceNeighborsQueryRunner(
            team=self.team,
            query=TraceNeighborsQuery(
                traceId="trace2",
                timestamp=datetime(2025, 1, 15, 1, 0, tzinfo=UTC).isoformat(),
                properties=[EventPropertyFilter(key="env", value="prod", operator=PropertyOperator.EXACT)],
            ),
        ).calculate()

        # Should skip trace3_dev and find trace4
        self.assertEqual(response.olderTraceId, "trace1")
        self.assertEqual(response.newerTraceId, "trace4")

    @freeze_time("2025-01-15T00:00:00Z")
    def test_filter_test_accounts(self):
        """Test that test account filtering works correctly."""
        self.team.test_account_filters = [
            {"key": "email", "value": "@test.com", "operator": "not_icontains", "type": "person"}
        ]
        self.team.save()

        _create_person(distinct_ids=["person_real"], team=self.team, properties={"email": "user@real.com"})
        _create_person(distinct_ids=["person_test"], team=self.team, properties={"email": "user@test.com"})

        # Create traces from both real and test users
        _create_ai_generation_event(
            distinct_id="person_real",
            trace_id="trace1_real",
            team=self.team,
            timestamp=datetime(2025, 1, 14, 0, 0, tzinfo=UTC),
        )
        _create_ai_generation_event(
            distinct_id="person_test",
            trace_id="trace2_test",
            team=self.team,
            timestamp=datetime(2025, 1, 14, 1, 0, tzinfo=UTC),
        )
        _create_ai_generation_event(
            distinct_id="person_real",
            trace_id="trace3_real",
            team=self.team,
            timestamp=datetime(2025, 1, 14, 2, 0, tzinfo=UTC),
        )

        # Query from trace3_real with test account filtering
        response = TraceNeighborsQueryRunner(
            team=self.team,
            query=TraceNeighborsQuery(
                traceId="trace3_real",
                timestamp=datetime(2025, 1, 14, 2, 0, tzinfo=UTC).isoformat(),
                filterTestAccounts=True,
            ),
        ).calculate()

        # Should skip trace2_test
        self.assertEqual(response.olderTraceId, "trace1_real")
        self.assertIsNone(response.newerTraceId)

    def test_only_trace_in_range(self):
        """Test behavior when there's only one trace in the date range."""
        _create_person(distinct_ids=["person1"], team=self.team)

        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace_only",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 0, tzinfo=UTC),
        )

        response = TraceNeighborsQueryRunner(
            team=self.team,
            query=TraceNeighborsQuery(
                traceId="trace_only",
                timestamp=datetime(2025, 1, 15, 0, 0, tzinfo=UTC).isoformat(),
            ),
        ).calculate()

        self.assertIsNone(response.olderTraceId)
        self.assertIsNone(response.olderTimestamp)
        self.assertIsNone(response.newerTraceId)
        self.assertIsNone(response.newerTimestamp)

    def test_multiple_event_types_in_trace(self):
        """Test that all AI event types are considered when finding neighbors."""
        _create_person(distinct_ids=["person1"], team=self.team)

        # trace1: only generation event
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 0, tzinfo=UTC),
        )

        # trace2: mix of event types
        _create_event(
            event="$ai_span",
            distinct_id="person1",
            properties={"$ai_trace_id": "trace2"},
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1, 0, tzinfo=UTC),
        )
        _create_event(
            event="$ai_metric",
            distinct_id="person1",
            properties={"$ai_trace_id": "trace2"},
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1, 30, tzinfo=UTC),
        )

        # trace3: feedback event
        _create_event(
            event="$ai_feedback",
            distinct_id="person1",
            properties={"$ai_trace_id": "trace3"},
            team=self.team,
            timestamp=datetime(2025, 1, 15, 2, 0, tzinfo=UTC),
        )

        # Query from trace2
        response = TraceNeighborsQueryRunner(
            team=self.team,
            query=TraceNeighborsQuery(
                traceId="trace2",
                timestamp=datetime(2025, 1, 15, 1, 30, tzinfo=UTC).isoformat(),
            ),
        ).calculate()

        self.assertEqual(response.olderTraceId, "trace1")
        self.assertEqual(response.newerTraceId, "trace3")

    def test_empty_trace_id_excluded(self):
        """Test that events with empty trace_id are excluded."""
        _create_person(distinct_ids=["person1"], team=self.team)

        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 0, tzinfo=UTC),
        )

        # Create event with empty trace_id
        _create_event(
            event="$ai_generation",
            distinct_id="person1",
            properties={"$ai_trace_id": ""},
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1, 0, tzinfo=UTC),
        )

        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace3",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 2, 0, tzinfo=UTC),
        )

        # Query from trace1
        response = TraceNeighborsQueryRunner(
            team=self.team,
            query=TraceNeighborsQuery(
                traceId="trace1",
                timestamp=datetime(2025, 1, 15, 0, 0, tzinfo=UTC).isoformat(),
            ),
        ).calculate()

        # Should skip the empty trace_id and find trace3
        self.assertEqual(response.newerTraceId, "trace3")

    def test_filter_support_traces(self):
        """Test that support traces can be filtered out."""
        _create_person(distinct_ids=["person1"], team=self.team)

        # Regular traces
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace1",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 0, 0, tzinfo=UTC),
        )

        # Support trace
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace2_support",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 1, 0, tzinfo=UTC),
            properties={"ai_support_impersonated": "true"},
        )

        # Regular trace
        _create_ai_generation_event(
            distinct_id="person1",
            trace_id="trace3",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 2, 0, tzinfo=UTC),
        )

        # Query from trace1 with support trace filtering
        response = TraceNeighborsQueryRunner(
            team=self.team,
            query=TraceNeighborsQuery(
                traceId="trace1",
                timestamp=datetime(2025, 1, 15, 0, 0, tzinfo=UTC).isoformat(),
                filterSupportTraces=True,
            ),
        ).calculate()

        # Should skip trace2_support
        self.assertEqual(response.newerTraceId, "trace3")
