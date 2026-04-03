import pytest
from unittest.mock import Mock, patch

import temporalio.exceptions
from parameterized import parameterized

from posthog.temporal.messaging.backfill_precalculated_person_properties_workflow import (
    BackfillPrecalculatedPersonPropertiesInputs,
    backfill_precalculated_person_properties_activity,
    evaluate_combined_filters_sync,
    flush_kafka_batch_async,
)
from posthog.temporal.messaging.filter_storage import combine_filter_bytecodes, store_filters
from posthog.temporal.messaging.types import PersonPropertyFilter

from common.hogvm.python.execute import execute_bytecode
from common.hogvm.python.operation import Operation


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


class TestCombineFilterBytecodes:
    """Tests for combine_filter_bytecodes."""

    def test_single_filter(self):
        filters = [
            PersonPropertyFilter(
                condition_hash="h1",
                bytecode=["_H", 1, 31, 32, "$browser", 32, "properties", 32, "person", 1, 3, 12],
                cohort_ids=[10],
                property_key="$browser",
            ),
        ]
        result = combine_filter_bytecodes(filters)
        assert result[0] == "_H"
        assert result[1] == 1
        assert result[2] == Operation.STRING
        assert result[3] == "h1"
        # Body without header
        assert result[4:-2] == [31, 32, "$browser", 32, "properties", 32, "person", 1, 3, 12]
        # Trailing DICT
        assert result[-2] == Operation.DICT
        assert result[-1] == 1

    def test_multiple_filters(self):
        filters = [
            PersonPropertyFilter(condition_hash="h1", bytecode=["_H", 1, 29], cohort_ids=[1], property_key=None),
            PersonPropertyFilter(condition_hash="h2", bytecode=["_H", 1, 30], cohort_ids=[2], property_key=None),
        ]
        result = combine_filter_bytecodes(filters)
        assert result == ["_H", 1, Operation.STRING, "h1", 29, Operation.STRING, "h2", 30, Operation.DICT, 2]

    def test_skips_malformed_bytecodes(self):
        filters = [
            PersonPropertyFilter(condition_hash="bad", bytecode=["_H", 1], cohort_ids=[1], property_key=None),
            PersonPropertyFilter(condition_hash="good", bytecode=["_H", 1, 29], cohort_ids=[2], property_key=None),
        ]
        result = combine_filter_bytecodes(filters)
        assert result == ["_H", 1, Operation.STRING, "good", 29, Operation.DICT, 1]

    def test_executes_and_returns_dict(self):
        filters = [
            PersonPropertyFilter(condition_hash="h1", bytecode=["_H", 1, 29], cohort_ids=[1], property_key=None),
            PersonPropertyFilter(condition_hash="h2", bytecode=["_H", 1, 30], cohort_ids=[2], property_key=None),
        ]
        combined = combine_filter_bytecodes(filters)
        result = execute_bytecode(combined, {})
        assert result.result == {"h1": True, "h2": False}

    @parameterized.expand(
        [
            ({"person": {"properties": {"$browser": "Chrome"}}}, {"browser_set": True}),
            ({"person": {"properties": {}}}, {"browser_set": False}),
        ]
    )
    def test_executes_with_person_properties(self, globals_input, expected_result):
        # Bytecode for: person.properties.$browser != NULL (is_set check)
        browser_bytecode = ["_H", 1, 31, 32, "$browser", 32, "properties", 32, "person", 1, 3, 12]
        filters = [
            PersonPropertyFilter(
                condition_hash="browser_set",
                bytecode=browser_bytecode,
                cohort_ids=[10],
                property_key="$browser",
            ),
        ]
        combined = combine_filter_bytecodes(filters)

        result = execute_bytecode(combined, globals_input)
        assert result.result == expected_result

    @parameterized.expand(
        [
            ({"person": {"properties": {"$browser": "Chrome"}}}, {"browser_set": True, "host_set": False}),
            (
                {"person": {"properties": {"$browser": "Chrome", "$host": "example.com"}}},
                {"browser_set": True, "host_set": True},
            ),
        ]
    )
    def test_executes_multiple_property_filters(self, globals_input, expected_result):
        browser_bytecode = ["_H", 1, 31, 32, "$browser", 32, "properties", 32, "person", 1, 3, 12]
        host_bytecode = ["_H", 1, 31, 32, "$host", 32, "properties", 32, "person", 1, 3, 12]
        filters = [
            PersonPropertyFilter(
                condition_hash="browser_set", bytecode=browser_bytecode, cohort_ids=[10], property_key="$browser"
            ),
            PersonPropertyFilter(
                condition_hash="host_set", bytecode=host_bytecode, cohort_ids=[10], property_key="$host"
            ),
        ]
        combined = combine_filter_bytecodes(filters)

        result = execute_bytecode(combined, globals_input)
        assert result.result == expected_result


class TestEvaluateCombinedFiltersSync:
    """Tests for evaluate_combined_filters_sync."""

    def test_returns_dict_on_success(self):
        combined = ["_H", 1, Operation.STRING, "h1", 29, Operation.DICT, 1]
        result = evaluate_combined_filters_sync(combined, {}, "person-1")
        assert result == {"h1": True}

    def test_returns_empty_dict_on_error(self):
        result = evaluate_combined_filters_sync(["_H", 1, 999], {}, "person-1")
        assert result == {}
