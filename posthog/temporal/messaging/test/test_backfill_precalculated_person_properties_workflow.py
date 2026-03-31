import asyncio

import pytest
from unittest.mock import Mock, patch

import temporalio.exceptions

from posthog.temporal.messaging.backfill_precalculated_person_properties_workflow import (
    BackfillPrecalculatedPersonPropertiesInputs,
    backfill_precalculated_person_properties_activity,
    flush_kafka_batch_async,
)


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

    @pytest.mark.asyncio
    async def test_successful_batch_flush(self):
        """Should await futures, flush producer, and return success count."""
        kafka_producer = Mock()
        logger = Mock()

        # Create mock futures that resolve successfully
        mock_futures: list[asyncio.Future[None]] = [asyncio.Future() for _ in range(3)]
        for future in mock_futures:
            future.set_result(None)  # Successful result

        with patch("posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.asyncio.to_thread"):
            result = await flush_kafka_batch_async(
                kafka_futures=mock_futures,
                kafka_producer=kafka_producer,
                team_id=1,
                logger=logger,
            )

        assert result == 3
        logger.info.assert_called()

    @pytest.mark.asyncio
    async def test_handles_exceptions_in_futures(self):
        """Should handle exceptions in futures gracefully."""
        kafka_producer = Mock()
        logger = Mock()

        # Create mix of successful and failed futures
        successful_future: asyncio.Future[None] = asyncio.Future()
        successful_future.set_result(None)

        failed_future: asyncio.Future[None] = asyncio.Future()
        failed_future.set_exception(Exception("Test error"))

        mock_futures = [successful_future, failed_future, successful_future]

        with patch("posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.asyncio.to_thread"):
            result = await flush_kafka_batch_async(
                kafka_futures=mock_futures,
                kafka_producer=kafka_producer,
                team_id=1,
                logger=logger,
            )

        # Should return count of successful futures only
        assert result == 2


class TestBackfillPrecalculatedPersonPropertiesActivity:
    """Tests for the main backfill activity function."""

    @pytest.mark.asyncio
    async def test_missing_filter_storage_key_raises_non_retryable_error(self):
        """Test that missing Redis key raises a non-retryable ApplicationError."""
        inputs = BackfillPrecalculatedPersonPropertiesInputs(
            team_id=1,
            filter_storage_key="backfill_person_properties_filters:team_1_nonexistent",
            cohort_ids=[100],
            batch_size=1,
        )

        # Mock get_filters_and_properties to return None (simulating missing/expired key)
        with patch(
            "posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.get_filters_and_properties"
        ) as mock_get_filters_and_properties:
            mock_get_filters_and_properties.return_value = None

            # Mock asyncio.to_thread to just call the function directly for testing
            with patch("asyncio.to_thread") as mock_to_thread:
                mock_to_thread.side_effect = lambda func, *args: func(*args)

                # Should raise non-retryable ApplicationError
                with pytest.raises(temporalio.exceptions.ApplicationError) as exc_info:
                    await backfill_precalculated_person_properties_activity(inputs)

                error = exc_info.value
                assert error.non_retryable is True
                assert error.type == "MissingFilters"
                assert "Filters not found in storage" in str(error)
                assert "Redis payload may have expired" in str(error)
                assert inputs.filter_storage_key in str(error)

    @pytest.mark.asyncio
    async def test_no_filters_aborts_early(self):
        """Should abort early and return zero results when no filters are found."""
        inputs = BackfillPrecalculatedPersonPropertiesInputs(
            team_id=1,
            filter_storage_key="backfill_person_properties_filters:team_1_empty",
            cohort_ids=[100],
            batch_size=1000,
        )

        # Mock get_filters_and_properties to return empty filters list
        with patch(
            "posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.get_filters_and_properties"
        ) as mock_get_filters_and_properties:
            mock_get_filters_and_properties.return_value = ([], [])  # Empty filters and properties

            # Mock asyncio.to_thread to just call the function directly for testing
            with patch("asyncio.to_thread") as mock_to_thread:
                mock_to_thread.side_effect = lambda func, *args: func(*args)

                result = await backfill_precalculated_person_properties_activity(inputs)

                # Should return zero results without processing
                assert result.persons_processed == 0
                assert result.events_produced == 0
                assert result.events_flushed == 0
                assert result.last_person_id is None
                assert result.duration_seconds == 0.0

    def test_property_names_with_backticks_generate_safe_query(self):
        """Should generate safe SQL queries when property names contain backticks or other dangerous characters."""
        # Test property names that could potentially break SQL queries
        dangerous_property_names = [
            "normal_prop",
            "prop`with`backticks",
            "`malicious`DROP TABLE person--",
            "prop`; DELETE FROM person; --",
        ]

        # Simulate the query building logic from the activity
        property_selects = []
        property_alias_mapping = {}

        for i, prop in enumerate(dangerous_property_names):
            # Use JSON extract to get only the specific property
            escaped_prop = prop.replace("'", "''")  # Escape single quotes for SQL safety
            safe_alias = f"prop_{i}"  # Use safe numeric aliases
            property_selects.append(f"JSONExtractString(properties, '{escaped_prop}') as `{safe_alias}`")
            property_alias_mapping[safe_alias] = prop

        properties_clause = ",\n                ".join(property_selects)

        # Build the full query
        query = f"""
            SELECT
                id as person_id,
                {properties_clause}
            FROM person FINAL
            WHERE team_id = %(team_id)s
              AND id > %(cursor)s
              AND is_deleted = 0
            ORDER BY id
            LIMIT %(batch_size)s
            FORMAT JSONEachRow
        """

        # Verify the query uses safe aliases instead of raw property names
        assert "prop_0" in query
        assert "prop_1" in query
        assert "prop_2" in query
        assert "prop_3" in query

        # Verify dangerous property names are NOT used as column aliases (but may appear in JSON paths)
        # The problem was that property names were used as column aliases like: ... as `dangerous_name`
        # Now they should only appear in JSON paths like: JSONExtractString(..., 'dangerous_name')
        assert "as `malicious`DROP TABLE person--`" not in query
        assert "as `prop`; DELETE FROM person; --`" not in query

        # Verify that dangerous property names appear safely in JSON extraction
        # (Single quotes are the only thing that needs escaping in JSON paths)
        assert "'prop`with`backticks'" in query  # Backticks are safe in JSON paths
        assert "'`malicious`DROP TABLE person--'" in query  # Only appears in JSON path, not as identifier

        # Verify alias mapping is correct
        assert property_alias_mapping["prop_0"] == "normal_prop"
        assert property_alias_mapping["prop_1"] == "prop`with`backticks"
        assert property_alias_mapping["prop_2"] == "`malicious`DROP TABLE person--"
        assert property_alias_mapping["prop_3"] == "prop`; DELETE FROM person; --"

        # Verify the new FINAL query structure
        assert "FROM person FINAL" in query
        assert "AND is_deleted = 0" in query
        assert "GROUP BY" not in query
        assert "HAVING" not in query
