import uuid
import datetime as dt

import pytest
from unittest.mock import MagicMock, Mock, patch

import temporalio.exceptions
from confluent_kafka import KafkaException
from parameterized import parameterized
from temporalio.testing import ActivityEnvironment

from posthog.clickhouse.client import sync_execute
from posthog.models.event.util import create_event
from posthog.temporal.messaging.backfill_precalculated_events_workflow import (
    BackfillPrecalculatedEventsInputs,
    backfill_precalculated_events_activity,
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

    @pytest.mark.asyncio
    async def test_raises_when_a_message_failed_to_deliver(self):
        # A failed delivery must surface as an error, not a silently-inflated success
        # count: the caller relies on this raising to retry the batch instead of treating
        # an undelivered row as corrected.
        kafka_producer = Mock()
        delivered = Mock()
        failed = Mock()
        failed.get.side_effect = KafkaException("broker not available")

        with patch(
            "posthog.temporal.messaging.backfill_precalculated_events_workflow.asyncio.to_thread"
        ) as mock_thread:
            mock_thread.return_value = None
            with pytest.raises(RuntimeError, match="1/2 messages"):
                await flush_kafka_batch_async(
                    kafka_results=[delivered, failed], kafka_producer=kafka_producer, team_id=1, logger=Mock()
                )


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


@pytest.mark.asyncio
@pytest.mark.django_db
class TestBackfillResolvesMergedPersons:
    async def test_backfill_resolves_person_id_through_overrides(self, team):
        old_person, new_person, plain_person = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        timestamp = dt.datetime(2024, 1, 1, 12, 0, tzinfo=dt.UTC)

        # Event ingested while did-merged still resolved to old_person; the distinct_id was
        # later merged onto new_person (recorded in person_distinct_id_overrides).
        merged_event_uuid = uuid.uuid4()
        create_event(merged_event_uuid, "$pageview", team, "did-merged", timestamp, person_id=old_person)
        sync_execute(
            """
            INSERT INTO person_distinct_id_overrides (team_id, distinct_id, person_id, version)
            VALUES
            """,
            [(team.pk, "did-merged", str(new_person), 1)],
        )
        # Control: never merged, must keep its ingestion-time person_id.
        plain_event_uuid = uuid.uuid4()
        create_event(plain_event_uuid, "$pageview", team, "did-plain", timestamp, person_id=plain_person)

        match_all_filter = BehavioralEventFilter(
            condition_hash="hash-1",
            bytecode=["_H", 1, Operation.TRUE],
            cohort_ids=[1],
            event_name="$pageview",
            time_value=30,
            time_interval="day",
        )
        inputs = BackfillPrecalculatedEventsInputs(
            team_id=team.pk,
            filter_storage_key="key",
            cohort_ids=[1],
            start_time="2024-01-01 00:00:00",
            end_time="2024-01-02 00:00:00",
        )

        mock_producer = MagicMock()
        with (
            patch(
                "posthog.temporal.messaging.backfill_precalculated_events_workflow.get_event_filters",
                return_value=([match_all_filter], ["$pageview"], {}),
            ),
            patch(
                "posthog.temporal.messaging.backfill_precalculated_events_workflow.get_producer",
                return_value=mock_producer,
            ),
        ):
            result = await ActivityEnvironment().run(backfill_precalculated_events_activity, inputs)

        assert result.events_processed == 2
        assert result.events_produced == 2

        person_id_by_event_uuid = {
            call.kwargs["data"]["uuid"]: call.kwargs["data"]["person_id"]
            for call in mock_producer.produce.call_args_list
        }
        assert person_id_by_event_uuid == {
            str(merged_event_uuid): str(new_person),
            str(plain_event_uuid): str(plain_person),
        }


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
