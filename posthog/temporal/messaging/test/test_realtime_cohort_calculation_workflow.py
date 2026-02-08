import pytest
from unittest.mock import Mock, patch

from posthog.temporal.messaging.realtime_cohort_calculation_workflow import flush_kafka_batch


class TestFlushKafkaBatch:
    """Tests for the flush_kafka_batch helper function."""

    @pytest.mark.asyncio
    async def test_empty_messages_returns_zero(self):
        """When pending_messages is empty, should return 0 without flushing."""
        kafka_producer = Mock()
        heartbeater = Mock()
        logger = Mock()

        result = await flush_kafka_batch(
            kafka_producer=kafka_producer,
            pending_messages=[],
            cohort_id=123,
            idx=1,
            total_cohorts=5,
            heartbeater=heartbeater,
            logger=logger,
        )

        assert result == 0
        kafka_producer.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_batch_flush(self):
        """Should flush messages and return batch size on success."""
        kafka_producer = Mock()
        kafka_producer.flush = Mock()

        # Mock successful send results
        mock_results = [Mock() for _ in range(100)]
        for mock_result in mock_results:
            mock_result.get = Mock(return_value=None)

        heartbeater = Mock()
        logger = Mock()

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow.asyncio.to_thread") as mock_thread:
            mock_thread.return_value = None

            result = await flush_kafka_batch(
                kafka_producer=kafka_producer,
                pending_messages=mock_results,
                cohort_id=123,
                idx=1,
                total_cohorts=5,
                heartbeater=heartbeater,
                logger=logger,
            )

        assert result == 100
        mock_thread.assert_called_once_with(kafka_producer.flush)
        logger.info.assert_called_once()

    @pytest.mark.asyncio
    async def test_final_batch_includes_final_in_messages(self):
        """When is_final=True, should include 'final' in heartbeat and log messages."""
        kafka_producer = Mock()
        mock_result = Mock()
        mock_result.get = Mock(return_value=None)

        heartbeater = Mock()
        logger = Mock()

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow.asyncio.to_thread"):
            await flush_kafka_batch(
                kafka_producer=kafka_producer,
                pending_messages=[mock_result],
                cohort_id=123,
                idx=1,
                total_cohorts=5,
                heartbeater=heartbeater,
                logger=logger,
                is_final=True,
            )

        # Check heartbeat details includes "final"
        assert heartbeater.details[0].startswith("Flushing final ")

        # Check logger includes "final"
        log_call_args = logger.info.call_args[0][0]
        assert "final" in log_call_args.lower()

    @pytest.mark.asyncio
    async def test_non_final_batch_excludes_final_from_messages(self):
        """When is_final=False, should not include 'final' in messages."""
        kafka_producer = Mock()
        mock_result = Mock()
        mock_result.get = Mock(return_value=None)

        heartbeater = Mock()
        logger = Mock()

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow.asyncio.to_thread"):
            await flush_kafka_batch(
                kafka_producer=kafka_producer,
                pending_messages=[mock_result],
                cohort_id=123,
                idx=1,
                total_cohorts=5,
                heartbeater=heartbeater,
                logger=logger,
                is_final=False,
            )

        # Check heartbeat details does not include "final"
        heartbeat_msg = heartbeater.details[0]
        assert "final" not in heartbeat_msg.lower()

        # Check logger does not include "final"
        log_call_args = logger.info.call_args[0][0]
        assert "final" not in log_call_args.lower()

    @pytest.mark.asyncio
    async def test_batch_flush_with_partial_failures(self):
        """Should raise exception when some messages fail to send."""
        kafka_producer = Mock()

        # Create mix of successful and failed results
        successful_result = Mock()
        successful_result.get = Mock(return_value=None)

        failed_result = Mock()
        failed_result.get = Mock(side_effect=Exception("Send failed"))

        mock_results = [successful_result, failed_result, successful_result]

        heartbeater = Mock()
        logger = Mock()

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow.asyncio.to_thread"):
            with pytest.raises(Exception, match="Failed to send 1/3 Kafka messages"):
                await flush_kafka_batch(
                    kafka_producer=kafka_producer,
                    pending_messages=mock_results,
                    cohort_id=123,
                    idx=1,
                    total_cohorts=5,
                    heartbeater=heartbeater,
                    logger=logger,
                )

        # Should log warnings for failed messages
        assert logger.warning.call_count == 1
        # Should log error summary
        assert logger.error.call_count == 1

    @pytest.mark.asyncio
    async def test_batch_flush_with_all_failures(self):
        """Should raise exception when all messages fail to send."""
        kafka_producer = Mock()

        # All results fail
        mock_results = []
        for _ in range(5):
            failed_result = Mock()
            failed_result.get = Mock(side_effect=Exception("Send failed"))
            mock_results.append(failed_result)

        heartbeater = Mock()
        logger = Mock()

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow.asyncio.to_thread"):
            with pytest.raises(Exception, match="Failed to send 5/5 Kafka messages"):
                await flush_kafka_batch(
                    kafka_producer=kafka_producer,
                    pending_messages=mock_results,
                    cohort_id=123,
                    idx=1,
                    total_cohorts=5,
                    heartbeater=heartbeater,
                    logger=logger,
                )

        assert logger.warning.call_count == 5
        assert logger.error.call_count == 1

    @pytest.mark.asyncio
    async def test_heartbeat_details_format(self):
        """Should format heartbeat details with cohort progress information."""
        kafka_producer = Mock()
        mock_result = Mock()
        mock_result.get = Mock(return_value=None)

        heartbeater = Mock()
        logger = Mock()

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow.asyncio.to_thread"):
            await flush_kafka_batch(
                kafka_producer=kafka_producer,
                pending_messages=[mock_result] * 10000,
                cohort_id=456,
                idx=3,
                total_cohorts=10,
                heartbeater=heartbeater,
                logger=logger,
            )

        heartbeat_msg = heartbeater.details[0]
        assert "10000 messages" in heartbeat_msg
        assert "cohort 3/10" in heartbeat_msg
        assert "cohort_id=456" in heartbeat_msg

    @pytest.mark.asyncio
    async def test_logger_includes_cohort_metadata(self):
        """Should include cohort_id and batch_size in logger metadata."""
        kafka_producer = Mock()
        mock_result = Mock()
        mock_result.get = Mock(return_value=None)

        heartbeater = Mock()
        logger = Mock()

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow.asyncio.to_thread"):
            await flush_kafka_batch(
                kafka_producer=kafka_producer,
                pending_messages=[mock_result] * 5000,
                cohort_id=789,
                idx=2,
                total_cohorts=8,
                heartbeater=heartbeater,
                logger=logger,
            )

        # Check logger.info was called with metadata
        logger.info.assert_called_once()
        call_kwargs = logger.info.call_args[1]
        assert call_kwargs["cohort_id"] == 789
        assert call_kwargs["batch_size"] == 5000


class TestBatchFlushingBehavior:
    """Tests for batch flushing logic and integration."""

    def test_flush_batch_size_constant_is_10k(self):
        """Verify the FLUSH_BATCH_SIZE constant is set to 10,000."""
        # Read the source to verify the constant
        import inspect

        import posthog.temporal.messaging.realtime_cohort_calculation_workflow as module

        source = inspect.getsource(module.process_realtime_cohort_calculation_activity)
        assert "FLUSH_BATCH_SIZE = 10_000" in source

    @pytest.mark.asyncio
    async def test_multiple_batches_handled_correctly(self):
        """Should handle multiple batch flushes correctly."""
        kafka_producer = Mock()

        # Simulate 3 batches: 10k, 10k, 5k
        heartbeater = Mock()
        logger = Mock()

        mock_results_batch1 = [Mock() for _ in range(10000)]
        mock_results_batch2 = [Mock() for _ in range(10000)]
        mock_results_batch3 = [Mock() for _ in range(5000)]

        for result in mock_results_batch1 + mock_results_batch2 + mock_results_batch3:
            result.get = Mock(return_value=None)

        with patch("posthog.temporal.messaging.realtime_cohort_calculation_workflow.asyncio.to_thread"):
            # Batch 1
            result1 = await flush_kafka_batch(kafka_producer, mock_results_batch1, 123, 1, 5, heartbeater, logger)
            # Batch 2
            result2 = await flush_kafka_batch(kafka_producer, mock_results_batch2, 123, 1, 5, heartbeater, logger)
            # Batch 3 (final)
            result3 = await flush_kafka_batch(
                kafka_producer, mock_results_batch3, 123, 1, 5, heartbeater, logger, is_final=True
            )

        assert result1 == 10000
        assert result2 == 10000
        assert result3 == 5000
        assert result1 + result2 + result3 == 25000
