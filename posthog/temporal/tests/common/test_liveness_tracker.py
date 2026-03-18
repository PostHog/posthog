import time

import pytest
from unittest.mock import AsyncMock, MagicMock

from temporalio.worker import ExecuteActivityInput, ExecuteWorkflowInput

from posthog.temporal.common.liveness_tracker import (
    LivenessTracker,
    _LivenessActivityInboundInterceptor,
    _LivenessWorkflowInterceptor,
    get_liveness_tracker,
)


class TestLivenessTracker:
    def test_initialization(self):
        """Test that tracker initializes with current time."""

        tracker = LivenessTracker()
        current_time = time.time()

        # Should be initialized to approximately now
        assert abs(tracker.get_last_execution_time() - current_time) < 1.0

    def test_record_activity_execution(self):
        """Test recording activity execution updates timestamp."""

        tracker = LivenessTracker()
        initial_time = tracker.get_last_execution_time()

        time.sleep(0.1)
        tracker.record_activity_execution()

        assert tracker.get_last_execution_time() > initial_time

    def test_record_workflow_execution(self):
        """Test recording workflow execution updates timestamp."""

        tracker = LivenessTracker()
        initial_time = tracker.get_last_execution_time()

        time.sleep(0.1)
        tracker.record_workflow_execution()

        assert tracker.get_last_execution_time() > initial_time

    def test_record_heartbeat(self):
        """Test recording heartbeat updates timestamp."""

        tracker = LivenessTracker()
        initial_time = tracker.get_last_execution_time()

        time.sleep(0.1)
        tracker.record_heartbeat()

        assert tracker.get_last_execution_time() > initial_time

    def test_get_last_execution_time_returns_most_recent(self):
        """Test that get_last_execution_time returns the most recent timestamp."""

        tracker = LivenessTracker()

        # Set activity to 2 seconds ago
        tracker._last_activity_time = time.time() - 2.0
        # Set workflow to 1 second ago
        tracker._last_workflow_time = time.time() - 1.0

        # Should return workflow time (most recent)
        last_time = tracker.get_last_execution_time()
        idle = time.time() - last_time
        assert 0.9 <= idle <= 1.1  # Should be about 1 second ago

    def test_is_healthy_when_within_threshold(self):
        """Test that tracker is healthy when execution is recent."""

        tracker = LivenessTracker()
        tracker.record_activity_execution()

        assert tracker.is_healthy(max_idle_seconds=10.0) is True

    def test_is_unhealthy_when_exceeds_threshold(self):
        """Test that tracker is unhealthy when idle exceeds threshold."""

        tracker = LivenessTracker()
        tracker._last_activity_time = time.time() - 11.0
        tracker._last_workflow_time = time.time() - 11.0

        assert tracker.is_healthy(max_idle_seconds=10.0) is False

    def test_get_idle_time(self):
        """Test that idle time is calculated correctly."""

        tracker = LivenessTracker()
        tracker._last_activity_time = time.time() - 5.0
        tracker._last_workflow_time = time.time() - 5.0

        idle_time = tracker.get_idle_time()
        assert 4.9 <= idle_time <= 5.1  # Should be about 5 seconds

    def test_thread_safety(self):
        """Test that tracker is thread-safe under concurrent access."""

        import threading

        tracker = LivenessTracker()
        results = []

        def record_activity():
            for _ in range(100):
                tracker.record_activity_execution()

        def record_workflow():
            for _ in range(100):
                tracker.record_workflow_execution()

        def record_heartbeat():
            for _ in range(100):
                tracker.record_heartbeat()

        def check_health():
            for _ in range(100):
                results.append(tracker.is_healthy(10.0))

        # Run multiple threads concurrently
        threads = [
            threading.Thread(target=record_activity),
            threading.Thread(target=record_workflow),
            threading.Thread(target=record_heartbeat),
            threading.Thread(target=check_health),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should not crash and should have recorded something
        assert tracker.get_idle_time() < 1.0
        assert len(results) == 100

    def test_get_liveness_tracker_returns_singleton(self):
        """Test that get_liveness_tracker returns the same instance."""

        tracker1 = get_liveness_tracker()
        tracker2 = get_liveness_tracker()

        assert tracker1 is tracker2


@pytest.mark.asyncio
class TestLivenessActivityInboundInterceptor:
    async def test_records_execution_on_success(self):
        """Test that activity execution is recorded on success."""

        tracker = LivenessTracker()
        tracker._last_activity_time = time.time() - 10.0

        # Create mock next interceptor
        next_interceptor = AsyncMock()
        next_interceptor.execute_activity.return_value = "result"

        interceptor = _LivenessActivityInboundInterceptor(next_interceptor)
        interceptor._tracker = tracker

        # Create mock input
        mock_input = MagicMock(spec=ExecuteActivityInput)

        # Execute
        result = await interceptor.execute_activity(mock_input)

        # Should have called next interceptor
        next_interceptor.execute_activity.assert_called_once_with(mock_input)

        # Should have recorded execution
        assert tracker.get_idle_time() < 1.0

        # Should return result
        assert result == "result"

    async def test_records_execution_on_failure(self):
        """Test that activity execution is recorded even on failure."""

        tracker = LivenessTracker()
        tracker._last_activity_time = time.time() - 10.0

        # Create mock next interceptor that raises
        next_interceptor = AsyncMock()
        next_interceptor.execute_activity.side_effect = ValueError("test error")

        interceptor = _LivenessActivityInboundInterceptor(next_interceptor)
        interceptor._tracker = tracker

        # Create mock input
        mock_input = MagicMock(spec=ExecuteActivityInput)

        # Execute and expect exception
        with pytest.raises(ValueError, match="test error"):
            await interceptor.execute_activity(mock_input)

        # Should still have recorded execution
        assert tracker.get_idle_time() < 1.0


@pytest.mark.asyncio
class TestLivenessWorkflowInterceptor:
    async def test_records_execution_on_success(self):
        """Test that workflow execution is recorded on success."""

        tracker = LivenessTracker()
        tracker._last_workflow_time = time.time() - 10.0

        # Create mock next interceptor
        next_interceptor = AsyncMock()
        next_interceptor.execute_workflow.return_value = "result"

        interceptor = _LivenessWorkflowInterceptor(next_interceptor)
        interceptor._tracker = tracker

        # Create mock input
        mock_input = MagicMock(spec=ExecuteWorkflowInput)

        # Execute
        result = await interceptor.execute_workflow(mock_input)

        # Should have called next interceptor
        next_interceptor.execute_workflow.assert_called_once_with(mock_input)

        # Should have recorded execution
        assert tracker.get_idle_time() < 1.0

        # Should return result
        assert result == "result"

    async def test_records_execution_on_failure(self):
        """Test that workflow execution is recorded even on failure."""

        tracker = LivenessTracker()
        tracker._last_workflow_time = time.time() - 10.0

        # Create mock next interceptor that raises
        next_interceptor = AsyncMock()
        next_interceptor.execute_workflow.side_effect = ValueError("test error")

        interceptor = _LivenessWorkflowInterceptor(next_interceptor)
        interceptor._tracker = tracker

        # Create mock input
        mock_input = MagicMock(spec=ExecuteWorkflowInput)

        # Execute and expect exception
        with pytest.raises(ValueError, match="test error"):
            await interceptor.execute_workflow(mock_input)

        # Should still have recorded execution
        assert tracker.get_idle_time() < 1.0
