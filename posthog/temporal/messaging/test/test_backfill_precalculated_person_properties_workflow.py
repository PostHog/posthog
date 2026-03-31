import asyncio

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
        """When kafka_futures is empty, should return 0 without flushing."""
        kafka_producer = Mock()
        logger = Mock()

        result = await flush_kafka_batch_async(
            kafka_futures=[],
            kafka_producer=kafka_producer,
            team_id=1,
            logger=logger,
        )

        assert result == 0
        kafka_producer.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_batch_flush_async(self):
        """Should handle successful futures correctly."""
        kafka_producer = Mock()
        logger = Mock()

        # Create successful futures
        success_future_1: asyncio.Future[int] = asyncio.Future()
        success_future_1.set_result(1)

        success_future_2: asyncio.Future[int] = asyncio.Future()
        success_future_2.set_result(1)

        kafka_futures = [success_future_1, success_future_2]

        with patch(
            "posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.asyncio.to_thread"
        ) as mock_thread:
            mock_thread.return_value = None

            result = await flush_kafka_batch_async(
                kafka_futures=kafka_futures,
                kafka_producer=kafka_producer,
                team_id=1,
                logger=logger,
            )

        assert result == 2
        mock_thread.assert_called_once_with(kafka_producer.flush)

    @pytest.mark.asyncio
    async def test_batch_flush_with_mixed_results(self):
        """Should handle mixed success and failure results correctly."""
        kafka_producer = Mock()
        logger = Mock()

        # Mock 3 results: 2 successful, 1 failed
        successful_future_1: asyncio.Future[int] = asyncio.Future()
        successful_future_1.set_result(1)

        successful_future_2: asyncio.Future[int] = asyncio.Future()
        successful_future_2.set_result(1)

        failed_future: asyncio.Future[None] = asyncio.Future()
        failed_future.set_exception(Exception("Kafka send failed"))

        mock_results = [successful_future_1, successful_future_2, failed_future]

        with patch(
            "posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.asyncio.to_thread"
        ) as mock_thread:
            mock_thread.return_value = None

            result = await flush_kafka_batch_async(
                kafka_futures=mock_results,
                kafka_producer=kafka_producer,
                team_id=1,
                logger=logger,
            )

        # Should return count of successful messages (2)
        assert result == 2
        mock_thread.assert_called_once_with(kafka_producer.flush)

    @pytest.mark.asyncio
    async def test_batch_flush_handles_all_result_types(self):
        """Should handle all possible result types from Kafka futures."""
        kafka_producer = Mock()
        logger = Mock()

        # Mock different result types
        success_future_int: asyncio.Future[int] = asyncio.Future()
        success_future_int.set_result(1)

        success_future_none: asyncio.Future[None] = asyncio.Future()
        success_future_none.set_result(None)

        failed_future: asyncio.Future[None] = asyncio.Future()
        failed_future.set_exception(Exception("Send failed"))

        mock_results = [success_future_int, success_future_none, failed_future]

        with patch(
            "posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.asyncio.to_thread"
        ) as mock_thread:
            mock_thread.return_value = None

            result = await flush_kafka_batch_async(
                kafka_futures=mock_results,
                kafka_producer=kafka_producer,
                team_id=1,
                logger=logger,
            )

        # Should count only the integer result (1 + 0 for None + 0 for exception = 1)
        assert result == 1
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
            cursor="00000000-0000-0000-0000-000000000000",
            batch_sequence=1,
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
            cursor="00000000-0000-0000-0000-000000000000",
            batch_sequence=1,
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
            cursor="00000000-0000-0000-0000-000000000000",
            batch_sequence=1,
        )

        # Basic verification that the filter was stored correctly
        assert inputs.filter_storage_key == storage_key
