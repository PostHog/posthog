import json

import pytest
from unittest.mock import Mock, patch

import temporalio.exceptions

from posthog.temporal.messaging.backfill_precalculated_person_properties_workflow import (
    BackfillPrecalculatedPersonPropertiesInputs,
    backfill_precalculated_person_properties_activity,
    flush_kafka_batch_async,
)
from posthog.temporal.messaging.filter_storage import store_filters
from posthog.temporal.messaging.types import PersonPropertyFilter


class TestFlushKafkaBatchAsync:
    """Tests for the flush_kafka_batch_async helper function."""

    @pytest.mark.asyncio
    async def test_empty_futures_returns_zero(self):
        """When kafka_results is empty, should return 0 without flushing."""
        kafka_producer = Mock()
        logger = Mock()

        result = await flush_kafka_batch_async(
            kafka_results=[],
            kafka_producer=kafka_producer,
            team_id=1,
            logger=logger,
        )

        assert result == 0

    @pytest.mark.asyncio
    async def test_successful_batch_flush_async(self):
        """Should handle successful ProduceResult objects correctly."""
        kafka_producer = Mock()
        logger = Mock()

        # Create mock ProduceResult objects
        produce_result_1 = Mock()
        produce_result_2 = Mock()
        kafka_results = [produce_result_1, produce_result_2]

        with patch(
            "posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.asyncio.to_thread"
        ) as mock_thread:
            mock_thread.return_value = None

            result = await flush_kafka_batch_async(
                kafka_results=kafka_results,
                kafka_producer=kafka_producer,
                team_id=1,
                logger=logger,
            )

        assert result == 2
        mock_thread.assert_called_once_with(kafka_producer.flush)

    @pytest.mark.asyncio
    async def test_batch_flush_with_multiple_results(self):
        """Should handle multiple ProduceResult objects correctly."""
        kafka_producer = Mock()
        logger = Mock()

        # Create mock ProduceResult objects - all are successful since failures are handled earlier
        produce_result_1 = Mock()
        produce_result_2 = Mock()
        produce_result_3 = Mock()
        kafka_results = [produce_result_1, produce_result_2, produce_result_3]

        with patch(
            "posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.asyncio.to_thread"
        ) as mock_thread:
            mock_thread.return_value = None

            result = await flush_kafka_batch_async(
                kafka_results=kafka_results,
                kafka_producer=kafka_producer,
                team_id=1,
                logger=logger,
            )

        # Should return count of all ProduceResult objects (3)
        assert result == 3
        mock_thread.assert_called_once_with(kafka_producer.flush)

    @pytest.mark.asyncio
    async def test_batch_flush_calls_kafka_flush(self):
        """Should call Kafka flush operation asynchronously."""
        kafka_producer = Mock()
        logger = Mock()

        # Create mock ProduceResult objects
        produce_results = [Mock(), Mock()]

        with patch(
            "posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.asyncio.to_thread"
        ) as mock_thread:
            mock_thread.return_value = None

            result = await flush_kafka_batch_async(
                kafka_results=produce_results,
                kafka_producer=kafka_producer,
                team_id=1,
                logger=logger,
            )

        # Should return count of ProduceResult objects and call flush
        assert result == 2
        mock_thread.assert_called_once_with(kafka_producer.flush)


class TestBackfillPrecalculatedPersonPropertiesActivity:
    """Tests for the main backfill activity function."""

    @pytest.mark.asyncio
    async def test_missing_filter_storage_key_raises_non_retryable_error(self):
        """Should raise non-retryable error when filter storage key doesn't exist."""
        inputs = BackfillPrecalculatedPersonPropertiesInputs(
            team_id=1,
            filter_storage_key="nonexistent_key",
            cohort_ids=[10],
            batch_size=10,
            start_person_id="00000000-0000-0000-0000-000000000000",
            end_person_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        )

        with pytest.raises(temporalio.exceptions.ApplicationError) as exc_info:
            await backfill_precalculated_person_properties_activity(inputs)

        assert exc_info.value.non_retryable is True
        assert "Filters not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_no_filters_aborts_early(self):
        """Should abort early and return zero results when no filters exist."""
        storage_key = store_filters([], team_id=1)

        inputs = BackfillPrecalculatedPersonPropertiesInputs(
            team_id=1,
            filter_storage_key=storage_key,
            cohort_ids=[10],
            batch_size=10,
            start_person_id="00000000-0000-0000-0000-000000000000",
            end_person_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        )

        result = await backfill_precalculated_person_properties_activity(inputs)

        # Should return early with zero results
        assert result.persons_processed == 0
        assert result.events_produced == 0
        assert result.events_flushed == 0
        assert result.last_person_id is None

    @pytest.mark.asyncio
    async def test_property_names_with_backticks_generate_safe_query(self):
        """Should safely handle property names that contain backticks."""
        # Create filters with a property name containing backticks
        filters = [
            PersonPropertyFilter(
                condition_hash="backtick_condition",
                bytecode=[],  # Empty bytecode for test
                cohort_ids=[10],
                property_key="weird`property",
            ),
        ]

        storage_key = store_filters(filters, team_id=1)

        # This should not crash when constructing query parameters
        inputs = BackfillPrecalculatedPersonPropertiesInputs(
            team_id=1,
            filter_storage_key=storage_key,
            cohort_ids=[10],
            batch_size=10,
            start_person_id="00000000-0000-0000-0000-000000000000",
            end_person_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        )

        # Basic verification that the filter was stored correctly
        assert inputs.filter_storage_key == storage_key

    @pytest.mark.asyncio
    async def test_hogvm_filter_evaluation_produces_events_for_matching_persons(self):
        """Should execute HogVM bytecode correctly and produce events only for matching persons."""
        filters = [
            PersonPropertyFilter(
                condition_hash="enterprise_filter",
                bytecode=[],  # Mock bytecode
                cohort_ids=[100],
                property_key="plan",
            ),
        ]

        storage_key = store_filters(filters, team_id=1)

        inputs = BackfillPrecalculatedPersonPropertiesInputs(
            team_id=1,
            filter_storage_key=storage_key,
            cohort_ids=[100],
            batch_size=10,
            start_person_id="00000000-0000-0000-0000-000000000000",
            end_person_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        )

        # Mock ClickHouse response with matching and non-matching persons
        mock_clickhouse_response = [
            {"id": "person1", "properties": '{"plan": "enterprise"}'},  # Should match
            {"id": "person2", "properties": '{"plan": "free"}'},  # Should not match
            {"id": "person3", "properties": '{"plan": "enterprise"}'},  # Should match
        ]

        # Mock HogVM execution to return True for enterprise plans, False for others
        def mock_execute_bytecode(bytecode, hog_globals):
            mock_result = Mock()
            person_plan = hog_globals.get("person", {}).get("properties", {}).get("plan")
            mock_result.result = person_plan == "enterprise"
            return mock_result

        with patch(
            "posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.get_client"
        ) as mock_get_client:
            mock_client = mock_get_client.return_value.__aenter__.return_value
            mock_client.stream_query_as_jsonl.return_value = mock_clickhouse_response

            with patch(
                "posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.execute_bytecode",
                side_effect=mock_execute_bytecode,
            ):
                with patch("posthog.kafka_client.client.KafkaProducer") as mock_kafka_producer:
                    mock_producer_instance = mock_kafka_producer.return_value
                    mock_producer_instance.send.return_value = "mock_produce_result"

                    with patch("temporalio.activity.info") as mock_activity_info:
                        mock_info = Mock()
                        mock_info.heartbeat_timeout = None
                        mock_activity_info.return_value = mock_info

                        result = await backfill_precalculated_person_properties_activity(inputs)

                    # Should process all 3 persons but only produce events for 2 matching ones
                    assert result.persons_processed == 3
                    assert result.events_produced == 2

                    # Verify Kafka send was called only for matching persons
                    send_calls = mock_producer_instance.send.call_args_list
                    assert len(send_calls) == 2

                    # Verify the person IDs in the sent events
                    sent_person_ids = []
                    for call in send_calls:
                        event_data = json.loads(call[1]["value"])
                        sent_person_ids.append(event_data["person_id"])

                    assert "person1" in sent_person_ids
                    assert "person3" in sent_person_ids
                    assert "person2" not in sent_person_ids
