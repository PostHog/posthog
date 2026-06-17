from contextlib import asynccontextmanager

import pytest
from unittest.mock import Mock, patch

import temporalio.exceptions
from parameterized import parameterized

from posthog.temporal.messaging.backfill_precalculated_events_workflow import (
    BackfillPrecalculatedEventsInputs,
    backfill_precalculated_events_activity,
    bytecode_references_properties,
    evaluate_event_combined_filters_sync,
    evaluate_event_filters_with_fallback_sync,
    evaluate_event_individual_filters_sync,
    flush_kafka_batch_async,
    parse_event_properties,
)
from posthog.temporal.messaging.types import BehavioralEventFilter

from common.hogvm.python.operation import Operation


class TestParseEventProperties:
    @parameterized.expand(
        [
            ("dict_input", {"key": "value"}, {"key": "value"}),
            ("json_string", '{"key": "value"}', {"key": "value"}),
            ("empty_dict", {}, {}),
            ("none_input", None, {}),
            ("invalid_json", "not json", {}),
            ("json_array", "[1, 2]", {}),
            ("json_number", "42", {}),
        ]
    )
    def test_parse_event_properties(self, _name, raw_input, expected):
        assert parse_event_properties(raw_input, "test-uuid") == expected


class TestBytecodeReferencesProperties:
    @parameterized.expand(
        [
            # Pure event-name filter (event == '$pageview') — never reads properties.
            (
                "event_name_only",
                [
                    "_H",
                    1,
                    Operation.STRING,
                    "$pageview",
                    Operation.STRING,
                    "event",
                    Operation.GET_GLOBAL,
                    1,
                    Operation.EQ,
                ],
                False,
            ),
            ("constant_true", ["_H", 1, Operation.TRUE], False),
            ("empty", [], False),
            # properties.foo access — the global root "properties" is a literal string operand.
            (
                "property_access",
                ["_H", 1, Operation.STRING, "foo", Operation.STRING, "properties", Operation.GET_GLOBAL, 2],
                True,
            ),
            # Nested (e.g. inside a declared function body) is still detected.
            ("nested", ["_H", 1, [Operation.STRING, "properties", Operation.GET_GLOBAL, 1]], True),
        ]
    )
    def test_detects_properties_reference(self, _name, bytecode, expected):
        assert bytecode_references_properties(bytecode) is expected


class TestFlushKafkaBatchAsync:
    @pytest.mark.asyncio
    async def test_empty_futures_returns_zero(self):
        result = await flush_kafka_batch_async(kafka_results=[], kafka_producer=Mock(), team_id=1, logger=Mock())
        assert result == 0

    @pytest.mark.asyncio
    async def test_successful_batch_flush(self):
        kafka_producer = Mock()
        kafka_results = [Mock(), Mock()]

        with patch(
            "posthog.temporal.messaging.backfill_precalculated_events_workflow.asyncio.to_thread"
        ) as mock_thread:
            mock_thread.return_value = None
            result = await flush_kafka_batch_async(
                kafka_results=kafka_results, kafka_producer=kafka_producer, team_id=1, logger=Mock()
            )

        assert result == 2
        mock_thread.assert_called_once_with(kafka_producer.flush)


class TestEvaluateEventCombinedFiltersSync:
    def test_returns_dict_result(self):
        # Bytecode that returns {"hash1": true}
        bytecode = ["_H", 1, Operation.STRING, "hash1", Operation.TRUE, Operation.DICT, 1]
        result = evaluate_event_combined_filters_sync(bytecode, {"event": "$pageview", "properties": {}}, "test-uuid")
        assert result == {"hash1": True}

    def test_returns_empty_on_non_dict(self):
        # Bytecode that returns a boolean instead of dict
        bytecode = ["_H", 1, Operation.TRUE]
        result = evaluate_event_combined_filters_sync(bytecode, {"event": "$pageview", "properties": {}}, "test-uuid")
        assert result == {}

    def test_returns_empty_on_error(self):
        result = evaluate_event_combined_filters_sync(
            ["_H", 1, Operation.STRING],  # Malformed bytecode
            {"event": "$pageview", "properties": {}},
            "test-uuid",
        )
        assert result == {}


class TestEvaluateEventIndividualFiltersSync:
    def test_evaluates_each_filter(self):
        filters = [
            BehavioralEventFilter(
                condition_hash="hash1",
                bytecode=["_H", 1, Operation.TRUE],
                cohort_ids=[1],
                event_name="$pageview",
                time_value=30,
                time_interval="day",
            ),
            BehavioralEventFilter(
                condition_hash="hash2",
                bytecode=["_H", 1, Operation.FALSE],
                cohort_ids=[2],
                event_name="$pageview",
                time_value=7,
                time_interval="day",
            ),
        ]
        result = evaluate_event_individual_filters_sync(filters, {"event": "$pageview", "properties": {}}, "test-uuid")
        assert result == {"hash1": True, "hash2": False}

    def test_skips_failed_filters(self):
        filters = [
            BehavioralEventFilter(
                condition_hash="hash1",
                bytecode=["_H", 1, Operation.TRUE],
                cohort_ids=[1],
                event_name="$pageview",
                time_value=30,
                time_interval="day",
            ),
            BehavioralEventFilter(
                condition_hash="hash_bad",
                bytecode=["_H", 1, Operation.STRING],  # Malformed
                cohort_ids=[2],
                event_name="$pageview",
                time_value=30,
                time_interval="day",
            ),
        ]
        result = evaluate_event_individual_filters_sync(filters, {"event": "$pageview", "properties": {}}, "test-uuid")
        assert result == {"hash1": True}


class TestEvaluateEventFiltersWithFallbackSync:
    def test_uses_combined_when_successful(self):
        bytecode = ["_H", 1, Operation.STRING, "hash1", Operation.TRUE, Operation.DICT, 1]
        filters = [
            BehavioralEventFilter(
                condition_hash="hash1",
                bytecode=["_H", 1, Operation.TRUE],
                cohort_ids=[1],
                event_name="$pageview",
                time_value=30,
                time_interval="day",
            ),
        ]
        result = evaluate_event_filters_with_fallback_sync(
            bytecode, filters, {"event": "$pageview", "properties": {}}, "test-uuid"
        )
        assert result == {"hash1": True}

    def test_falls_back_on_combined_error(self):
        bad_bytecode = ["_H", 1, Operation.STRING]  # Malformed
        filters = [
            BehavioralEventFilter(
                condition_hash="hash1",
                bytecode=["_H", 1, Operation.TRUE],
                cohort_ids=[1],
                event_name="$pageview",
                time_value=30,
                time_interval="day",
            ),
        ]
        result = evaluate_event_filters_with_fallback_sync(
            bad_bytecode, filters, {"event": "$pageview", "properties": {}}, "test-uuid"
        )
        assert result == {"hash1": True}


class TestBackfillPrecalculatedEventsActivity:
    @pytest.mark.asyncio
    async def test_missing_filters_raises_non_retryable(self):
        inputs = BackfillPrecalculatedEventsInputs(
            team_id=1,
            filter_storage_key="nonexistent_key",
            cohort_ids=[1],
            start_time="2024-01-01T00:00:00+00:00",
            end_time="2024-01-02T00:00:00+00:00",
        )

        with (
            patch(
                "posthog.temporal.messaging.backfill_precalculated_events_workflow.get_event_filters",
                return_value=None,
            ),
            patch(
                "posthog.temporal.messaging.backfill_precalculated_events_workflow.asyncio.to_thread",
                side_effect=lambda fn, *args: fn(*args),
            ),
            pytest.raises(temporalio.exceptions.ApplicationError, match="Event filters not found"),
        ):
            await backfill_precalculated_events_activity(inputs)

    @pytest.mark.asyncio
    async def test_empty_filters_returns_zero(self):
        inputs = BackfillPrecalculatedEventsInputs(
            team_id=1,
            filter_storage_key="some_key",
            cohort_ids=[1],
            start_time="2024-01-01T00:00:00+00:00",
            end_time="2024-01-02T00:00:00+00:00",
        )

        with (
            patch(
                "posthog.temporal.messaging.backfill_precalculated_events_workflow.get_event_filters",
                return_value=([], [], {}),
            ),
            patch(
                "posthog.temporal.messaging.backfill_precalculated_events_workflow.asyncio.to_thread",
                side_effect=lambda fn, *args: fn(*args),
            ),
        ):
            result = await backfill_precalculated_events_activity(inputs)

        assert result.events_processed == 0
        assert result.events_produced == 0

    async def _run_activity_capturing_query(self, filters, event_names, combined_bytecodes, rows):
        """Run the activity with ClickHouse/Kafka mocked, returning (executed_query, result)."""
        captured: dict[str, str] = {}

        async def fake_stream(query, query_parameters=None):
            captured["query"] = query
            for row in rows:
                yield row

        mock_client = Mock()
        mock_client.stream_query_as_jsonl = fake_stream

        @asynccontextmanager
        async def fake_get_client(**_kwargs):
            yield mock_client

        @asynccontextmanager
        async def fake_heartbeater(**_kwargs):
            yield Mock(details=None)

        inputs = BackfillPrecalculatedEventsInputs(
            team_id=1,
            filter_storage_key="some_key",
            cohort_ids=[1],
            start_time="2024-01-01T00:00:00+00:00",
            end_time="2024-01-02T00:00:00+00:00",
        )

        module = "posthog.temporal.messaging.backfill_precalculated_events_workflow"
        with (
            patch(f"{module}.get_event_filters", return_value=(filters, event_names, combined_bytecodes)),
            patch(f"{module}.get_producer", return_value=Mock()),
            patch(f"{module}.get_client", fake_get_client),
            patch(f"{module}.Heartbeater", fake_heartbeater),
            patch(f"{module}.asyncio.to_thread", side_effect=lambda fn, *args, **kwargs: fn(*args, **kwargs)),
        ):
            result = await backfill_precalculated_events_activity(inputs)

        return captured["query"], result

    @pytest.mark.asyncio
    async def test_skips_properties_column_when_no_filter_reads_properties(self):
        # Pure event-name filter — bytecode never references properties.
        bytecode = ["_H", 1, Operation.TRUE]
        filters = [
            BehavioralEventFilter(
                condition_hash="hash1",
                bytecode=bytecode,
                cohort_ids=[1],
                event_name="$pageview",
                time_value=30,
                time_interval="day",
            )
        ]
        rows = [{"uuid": "u1", "event": "$pageview", "date": "2024-01-01", "distinct_id": "d1", "person_id": "p1"}]

        query, result = await self._run_activity_capturing_query(filters, ["$pageview"], {}, rows)

        assert "properties" not in query
        # The row carries no properties column, yet evaluation still runs and matches.
        assert result.events_processed == 1

    @pytest.mark.asyncio
    async def test_reads_properties_column_when_a_filter_references_properties(self):
        # properties.foo access — "properties" appears in the bytecode.
        bytecode = ["_H", 1, Operation.STRING, "foo", Operation.STRING, "properties", Operation.GET_GLOBAL, 2]
        filters = [
            BehavioralEventFilter(
                condition_hash="hash1",
                bytecode=bytecode,
                cohort_ids=[1],
                event_name="$pageview",
                time_value=30,
                time_interval="day",
            )
        ]
        rows = [
            {
                "uuid": "u1",
                "event": "$pageview",
                "date": "2024-01-01",
                "distinct_id": "d1",
                "person_id": "p1",
                "properties": "{}",
            }
        ]

        query, result = await self._run_activity_capturing_query(filters, ["$pageview"], {}, rows)

        assert "properties" in query
        assert result.events_processed == 1


class TestBackfillPrecalculatedEventsInputs:
    def test_properties_to_log(self):
        inputs = BackfillPrecalculatedEventsInputs(
            team_id=1,
            filter_storage_key="key",
            cohort_ids=[1, 2, 3],
            start_time="2024-01-01T00:00:00+00:00",
            end_time="2024-01-02T00:00:00+00:00",
        )
        props = inputs.properties_to_log
        assert props["team_id"] == 1
        assert props["cohort_count"] == 3
        assert props["start_time"] == "2024-01-01T00:00:00+00:00"
        assert props["end_time"] == "2024-01-02T00:00:00+00:00"
