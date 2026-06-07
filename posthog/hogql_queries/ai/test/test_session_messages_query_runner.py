import json
import uuid
from datetime import UTC, datetime
from typing import Any

from freezegun import freeze_time
from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    cleanup_materialized_columns,
    flush_persons_and_events,
)
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, MaterializationMode, SessionMessagesQuery

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.placeholders import replace_placeholders
from posthog.hogql.printer import prepare_and_print_ast

from posthog.clickhouse.client.execute import sync_execute
from posthog.hogql_queries.ai.ai_column_rewriter import rewrite_expr_for_events_table, rewrite_query_for_events_table
from posthog.hogql_queries.ai.session_messages_query_runner import SessionMessagesQueryRunner
from posthog.models.ai_events.test_util import bulk_create_ai_events

from ee.clickhouse.materialized_columns.columns import get_bloom_filter_index_name, materialize


def _skip_indexes_in_plan(plan_json: Any) -> set[str]:
    """Walk a ClickHouse EXPLAIN PLAN JSON and return the names of all Skip-type indexes used."""
    out: set[str] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if isinstance(obj.get("Indexes"), list):
                for idx in obj["Indexes"]:
                    if isinstance(idx, dict) and idx.get("Type") == "Skip" and isinstance(idx.get("Name"), str):
                        out.add(idx["Name"])
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(plan_json)
    return out


def _gen_event_payload(
    *,
    session_id: str,
    trace_id: str,
    team,
    distinct_id: str = "person1",
    timestamp: datetime,
    event: str = "$ai_generation",
    extra_properties: dict | None = None,
    event_uuid: str | None = None,
) -> dict:
    properties = {
        "$ai_session_id": session_id,
        "$ai_trace_id": trace_id,
        "$ai_input": [{"role": "user", "content": f"hi {trace_id}"}],
        "$ai_output_choices": [{"role": "assistant", "content": f"hello {trace_id}"}],
    }
    if extra_properties:
        properties.update(extra_properties)
    return {
        "event": event,
        "distinct_id": distinct_id,
        "team": team,
        "timestamp": timestamp,
        "properties": properties,
        "event_uuid": event_uuid or str(uuid.uuid4()),
    }


@freeze_time("2025-01-15T12:00:00Z")
class TestSessionMessagesQueryRunner(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        _create_person(distinct_ids=["person1"], team=self.team)

    @patch("posthog.hogql_queries.ai.ai_table_resolver.is_ai_events_enabled", return_value=True)
    def test_ai_events_happy_path_groups_by_trace_with_heavy_columns(self, _mock_flag):
        session_id = "session-happy"
        # Two events per trace (one minute apart) across three traces → six rows.
        bulk_create_ai_events(
            [
                _gen_event_payload(
                    session_id=session_id,
                    trace_id=trace_id,
                    team=self.team,
                    timestamp=datetime(2025, 1, 15, 10, minute, tzinfo=UTC),
                )
                for trace_id in ("trace-a", "trace-b", "trace-c")
                for minute in (0, 1)
            ]
        )

        response = SessionMessagesQueryRunner(
            team=self.team,
            query=SessionMessagesQuery(sessionId=session_id),
        ).calculate()

        assert len(response.results) == 6
        trace_ids = {event.properties.get("$ai_trace_id") for event in response.results}
        assert trace_ids == {"trace-a", "trace-b", "trace-c"}

        for event in response.results:
            assert event.event == "$ai_generation"
            # Heavy columns merged back into properties (the whole point of this runner).
            assert event.properties["$ai_input"] == [
                {"role": "user", "content": f"hi {event.properties['$ai_trace_id']}"}
            ]
            assert event.properties["$ai_output_choices"] == [
                {"role": "assistant", "content": f"hello {event.properties['$ai_trace_id']}"}
            ]

    @patch("posthog.hogql_queries.ai.ai_table_resolver.is_ai_events_enabled", return_value=False)
    def test_kill_switch_off_reads_events_directly(self, _mock_flag):
        # ai-events-table-rollout flag off: the runner bypasses ai_events and serves the
        # session from the shared events table. Covers both the emergency rollback lever
        # and non-migrated teams (whose flag is simply off).
        session_id = "session-killswitch"
        _create_event(
            event="$ai_generation",
            distinct_id="person1",
            team=self.team,
            timestamp=datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
            properties={
                "$ai_session_id": session_id,
                "$ai_trace_id": "trace-killed",
                "$ai_input": [{"role": "user", "content": "kill switch off"}],
            },
        )

        response = SessionMessagesQueryRunner(
            team=self.team,
            query=SessionMessagesQuery(sessionId=session_id),
        ).calculate()

        assert len(response.results) == 1
        assert response.results[0].properties["$ai_trace_id"] == "trace-killed"

    @patch("posthog.hogql_queries.ai.ai_table_resolver.is_ai_events_enabled", return_value=True)
    def test_empty_session_returns_no_rows(self, _mock_flag):
        response = SessionMessagesQueryRunner(
            team=self.team,
            query=SessionMessagesQuery(sessionId="session-does-not-exist"),
        ).calculate()
        assert response.results == []

    @parameterized.expand(
        [
            # Transcript types are kept (guards against narrowing _SESSION_TRANSCRIPT_EVENT_NAMES).
            ("generation_kept", {"event": "$ai_generation"}, True),
            ("span_kept", {"event": "$ai_span"}, True),
            ("trace_kept", {"event": "$ai_trace"}, True),
            ("embedding_kept", {"event": "$ai_embedding"}, True),
            # Non-transcript types are never rendered on the sessions page (verified against
            # 30d of prod data — see runner docstring), so they're filtered out.
            ("metric_excluded", {"event": "$ai_metric"}, False),
            ("feedback_excluded", {"event": "$ai_feedback"}, False),
            ("evaluation_excluded", {"event": "$ai_evaluation"}, False),
            # Session-scoped span with no trace_id — isolates the `trace_id != ''` clause.
            ("empty_trace_id_excluded", {"event": "$ai_span", "trace_id": ""}, False),
        ]
    )
    @patch("posthog.hogql_queries.ai.ai_table_resolver.is_ai_events_enabled", return_value=True)
    def test_row_filtering(self, name, overrides, should_be_returned, _mock_flag):
        session_id = f"session-{name}"
        payload = {
            "session_id": session_id,
            "trace_id": "trace-1",
            "team": self.team,
            "timestamp": datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
            **overrides,
        }
        bulk_create_ai_events([_gen_event_payload(**payload)])

        response = SessionMessagesQueryRunner(
            team=self.team,
            query=SessionMessagesQuery(sessionId=session_id),
        ).calculate()

        if should_be_returned:
            assert len(response.results) == 1
            assert response.results[0].event == overrides["event"]
        else:
            assert response.results == []

    @patch("posthog.hogql_queries.ai.ai_table_resolver.is_ai_events_enabled", return_value=True)
    def test_isolates_sessions(self, _mock_flag):
        # Returns the session that is queried against
        bulk_create_ai_events(
            [
                _gen_event_payload(
                    session_id="session-a",
                    trace_id="trace-a1",
                    team=self.team,
                    timestamp=datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
                ),
                _gen_event_payload(
                    session_id="session-b",
                    trace_id="trace-b1",
                    team=self.team,
                    timestamp=datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
                ),
            ]
        )

        response = SessionMessagesQueryRunner(
            team=self.team,
            query=SessionMessagesQuery(sessionId="session-a"),
        ).calculate()

        assert len(response.results) == 1
        assert response.results[0].properties["$ai_trace_id"] == "trace-a1"

    @patch("posthog.hogql_queries.ai.ai_table_resolver.is_ai_events_enabled", return_value=True)
    def test_returns_all_kept_transcript_event_types(self, _mock_flag):
        # Guards against accidentally narrowing _SESSION_TRANSCRIPT_EVENT_NAMES or
        # tightening the WHERE clause in a way that drops a kept type.
        session_id = "session-mixed"
        kept_types = ["$ai_generation", "$ai_span", "$ai_trace", "$ai_embedding"]
        bulk_create_ai_events(
            [
                _gen_event_payload(
                    session_id=session_id,
                    trace_id="trace-mixed",
                    team=self.team,
                    timestamp=datetime(2025, 1, 15, 10, i, tzinfo=UTC),
                    event=event_type,
                )
                for i, event_type in enumerate(kept_types)
            ]
        )

        response = SessionMessagesQueryRunner(
            team=self.team,
            query=SessionMessagesQuery(sessionId=session_id),
        ).calculate()

        returned_types = {event.event for event in response.results}
        assert returned_types == set(kept_types)

    @patch("posthog.hogql_queries.ai.ai_table_resolver.is_ai_events_enabled", return_value=True)
    def test_applies_no_time_bound(self, _mock_flag):
        # The session-id lookup is bloom-filter indexed, so the runner applies no timestamp
        # filter — the ai_events TTL bounds retention at the storage layer. An event far
        # older than the 30-day lookback the previous implementation enforced is still
        # returned (guards against a date filter creeping back into the WHERE clause).
        session_id = "session-ancient"
        bulk_create_ai_events(
            [
                _gen_event_payload(
                    session_id=session_id,
                    trace_id="trace-ancient",
                    team=self.team,
                    # ~7 months before the frozen "now" of 2025-01-15.
                    timestamp=datetime(2024, 6, 1, tzinfo=UTC),
                ),
            ]
        )

        response = SessionMessagesQueryRunner(
            team=self.team,
            query=SessionMessagesQuery(sessionId=session_id),
        ).calculate()

        assert len(response.results) == 1
        assert response.results[0].properties["$ai_trace_id"] == "trace-ancient"

    @patch("posthog.hogql_queries.ai.ai_table_resolver.is_ai_events_enabled", return_value=True)
    def test_merges_all_six_heavy_columns_into_properties(self, _mock_flag):
        # The central behavioral contract: every heavy AI property stripped from the
        # JSON blob into a dedicated column must be folded back into `properties`.
        session_id = "session-heavy"
        heavy_values = {
            "$ai_input": [{"role": "user", "content": "ask"}],
            "$ai_output": "raw response",
            "$ai_output_choices": [{"role": "assistant", "content": "reply"}],
            "$ai_input_state": {"step": "start"},
            "$ai_output_state": {"step": "done"},
            "$ai_tools": [{"name": "search"}],
        }
        bulk_create_ai_events(
            [
                {
                    "event": "$ai_generation",
                    "distinct_id": "person1",
                    "team": self.team,
                    "timestamp": datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
                    "properties": {
                        "$ai_session_id": session_id,
                        "$ai_trace_id": "trace-heavy",
                        **heavy_values,
                    },
                    "event_uuid": str(uuid.uuid4()),
                }
            ]
        )

        response = SessionMessagesQueryRunner(
            team=self.team,
            query=SessionMessagesQuery(sessionId=session_id),
        ).calculate()

        assert len(response.results) == 1
        properties = response.results[0].properties
        for key, expected in heavy_values.items():
            assert properties[key] == expected, f"{key} not merged correctly"


class TestSessionMessagesEventsFallbackIndex(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        _create_person(distinct_ids=["person1"], team=self.team)
        cleanup_materialized_columns()
        self.addCleanup(cleanup_materialized_columns)

    def test_events_fallback_filters_on_session_id_bloom_filter(self):
        # The events-table fallback (non-migrated teams / sessions fully aged past the ai_events TTL)
        # must filter on the bloom-filter-indexed materialized $ai_session_id column, not a JSON
        # extraction. Because the runner applies no time bound, defeating this index turns the query
        # into a full scan of the team's entire events history (measured at ~6 TiB / ~50s on a busy
        # prod team). This asserts the column rewriter + printer keep routing session_id to the index.
        for i in range(12):
            _create_event(
                event="$ai_generation",
                distinct_id="person1",
                team=self.team,
                timestamp=datetime(2025, 1, 15, 10, i, tzinfo=UTC),
                properties={"$ai_session_id": f"seed-{i}", "$ai_trace_id": f"trace-{i}"},
            )
        flush_persons_and_events()
        # Mirror migration 0161: nullable materialized $ai_session_id column with a bloom filter.
        mat_col = materialize(
            "events",
            "$ai_session_id",
            table_column="properties",
            is_nullable=True,
            create_bloom_filter_index=True,
        )

        # Build the exact query the runner hands to the events fallback path.
        runner = SessionMessagesQueryRunner(team=self.team, query=SessionMessagesQuery(sessionId="seed-5"))
        events_query = rewrite_query_for_events_table(runner._build_query())
        events_placeholders = {k: rewrite_expr_for_events_table(v) for k, v in runner._build_placeholders().items()}
        prepared = replace_placeholders(events_query, events_placeholders)

        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            enable_select_queries=True,
            modifiers=HogQLQueryModifiers(materializationMode=MaterializationMode.AUTO),
        )
        sql, _ = prepare_and_print_ast(prepared, context, "clickhouse")

        # Replicate the runtime settings — skip-index selection diverges without them.
        settings = {
            k: "1" if v is True else "0" if v is False else str(v)
            for k, v in HogQLGlobalSettings().model_dump().items()
            if v is not None
        }
        [[raw_plan]] = sync_execute(f"EXPLAIN indexes = 1, json = 1 {sql}", context.values, settings=settings)
        used = _skip_indexes_in_plan(json.loads(raw_plan))

        index_name = get_bloom_filter_index_name(mat_col.name)
        assert index_name in used, (
            f"events fallback no longer prunes on the $ai_session_id bloom filter; "
            f"ClickHouse used {sorted(used)}.\nSQL: {sql}"
        )
