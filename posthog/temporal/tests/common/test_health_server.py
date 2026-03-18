import time
import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from freezegun import freeze_time

from aiohttp import ClientSession

from posthog.temporal.common.health_server import HealthCheckServer
from posthog.temporal.common.liveness_tracker import LivenessTracker


@asynccontextmanager
async def create_server(tracker: LivenessTracker, port: int = 18001, max_idle_seconds: float = 2.0):
    server = HealthCheckServer(port=port, liveness_tracker=tracker, max_idle_seconds=max_idle_seconds)
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


@pytest.mark.asyncio
class TestHealthCheckServer:
    async def test_healthz_returns_healthy_when_recently_active(self):
        """Test that /healthz returns 200 when activity was recent."""

        tracker = LivenessTracker()
        async with create_server(tracker):
            # Record activity
            tracker.record_activity_execution()

            async with ClientSession() as session:
                async with session.get("http://localhost:18001/healthz") as response:
                    assert response.status == 200
                    data = await response.json()
                    assert data["status"] == "healthy"
                    assert data["idle_seconds"] < 1.0
                    assert data["max_idle_seconds"] == 2.0

    @freeze_time("2024-01-01 12:00:00")
    async def test_healthz_returns_unhealthy_when_idle_too_long(self):
        """Test that /healthz returns 503 when idle time exceeds threshold."""

        tracker = LivenessTracker()
        async with create_server(tracker):
            # Set activity time to 3 seconds ago (threshold is 2 seconds)
            tracker._last_activity_time = time.time() - 3.0
            tracker._last_workflow_time = time.time() - 3.0

            async with ClientSession() as session:
                async with session.get("http://localhost:18001/healthz") as response:
                    assert response.status == 503
                    data = await response.json()
                    assert data["status"] == "unhealthy"
                    assert data["idle_seconds"] == 3.0
                    assert data["max_idle_seconds"] == 2.0
                    assert "No workflow/activity execution" in data["message"]

    async def test_healthz_considers_workflow_execution(self):
        """Test that workflow execution also keeps the worker healthy."""

        tracker = LivenessTracker()
        async with create_server(tracker):
            tracker.record_workflow_execution()

            async with ClientSession() as session:
                async with session.get("http://localhost:18001/healthz") as response:
                    assert response.status == 200
                    data = await response.json()
                    assert data["status"] == "healthy"

    async def test_healthz_considers_heartbeats(self):
        """Test that heartbeats keep the worker healthy during long-running activities."""

        tracker = LivenessTracker()
        async with create_server(tracker):
            tracker.record_heartbeat()

            async with ClientSession() as session:
                async with session.get("http://localhost:18001/healthz") as response:
                    assert response.status == 200
                    data = await response.json()
                    assert data["status"] == "healthy"

    async def test_healthz_uses_most_recent_timestamp(self):
        """Test that healthz uses the most recent of activity or workflow time."""

        tracker = LivenessTracker()
        async with create_server(tracker):
            # Set activity to 3 seconds ago
            tracker._last_activity_time = time.time() - 3.0
            # Set workflow to just now
            tracker.record_workflow_execution()

            async with ClientSession() as session:
                async with session.get("http://localhost:18001/healthz") as response:
                    assert response.status == 200
                    data = await response.json()
                    assert data["status"] == "healthy"
                    assert data["idle_seconds"] < 1.0

    async def test_readyz_returns_same_as_healthz(self):
        """Test that /readyz returns the same status as /healthz."""

        tracker = LivenessTracker()
        async with create_server(tracker):
            tracker.record_activity_execution()

            async with ClientSession() as session:
                async with session.get("http://localhost:18001/readyz") as response:
                    assert response.status == 200
                    data = await response.json()
                    assert data["status"] == "healthy"

    async def test_unknown_path_returns_404(self):
        """Test that unknown paths return 404."""

        tracker = LivenessTracker()
        async with create_server(tracker):
            async with ClientSession() as session:
                async with session.get("http://localhost:18001/unknown") as response:
                    assert response.status == 404

    async def test_server_can_be_started_and_stopped(self):
        """Test that server can be cleanly started and stopped."""

        tracker = LivenessTracker()
        server = HealthCheckServer(port=18002, liveness_tracker=tracker, max_idle_seconds=2.0)

        # Start the server
        await server.start()

        # Verify it's accessible
        async with ClientSession() as session:
            async with session.get("http://localhost:18002/healthz") as response:
                assert response.status == 200

        # Stop the server
        await server.stop()

        # Verify it's no longer accessible
        from aiohttp import ClientTimeout

        with pytest.raises(Exception):  # Connection error
            async with ClientSession() as session:
                async with session.get("http://localhost:18002/healthz", timeout=ClientTimeout(total=1)) as response:
                    pass

    async def test_server_cannot_be_started_twice(self):
        """Test that starting an already-started server raises an error."""

        tracker = LivenessTracker()
        async with create_server(tracker) as server:
            with pytest.raises(RuntimeError, match="Server already started"):
                await server.start()

    async def test_stopping_unstarted_server_is_safe(self):
        """Test that stopping a server that was never started doesn't error."""

        tracker = LivenessTracker()
        server = HealthCheckServer(port=18003, liveness_tracker=tracker, max_idle_seconds=2.0)
        await server.stop()  # Should not raise

    async def test_healthz_handles_concurrent_requests(self):
        """Test that the server can handle multiple concurrent health checks."""

        tracker = LivenessTracker()
        async with create_server(tracker):
            tracker.record_activity_execution()

            async def check_health():
                async with ClientSession() as session:
                    async with session.get("http://localhost:18001/healthz") as response:
                        assert response.status == 200
                        return await response.json()

            # Make 10 concurrent requests
            results = await asyncio.gather(*[check_health() for _ in range(10)])

            # All should succeed
            assert len(results) == 10
            assert all(r["status"] == "healthy" for r in results)

    async def test_idle_time_accuracy(self):
        """Test that idle_time is calculated accurately."""

        with freeze_time("2024-01-01 12:00:00") as frozen_time:
            tracker = LivenessTracker()
            async with create_server(tracker):
                # Record activity at t=0
                tracker.record_activity_execution()

                # Move time forward 0.5 seconds
                frozen_time.tick(timedelta(seconds=0.5))

                async with ClientSession() as session:
                    async with session.get("http://localhost:18001/healthz") as response:
                        data = await response.json()
                        # Should be exactly 0.5 seconds
                        assert data["idle_seconds"] == 0.5

    async def test_healthz_transition_from_healthy_to_unhealthy(self):
        """Test that health status changes as time passes."""

        with freeze_time("2024-01-01 12:00:00") as frozen_time:
            tracker = LivenessTracker()
            async with create_server(tracker):
                tracker.record_activity_execution()

                # Should be healthy immediately
                async with ClientSession() as session:
                    async with session.get("http://localhost:18001/healthz") as response:
                        assert response.status == 200

                # Move time forward past threshold (2 seconds + buffer)
                frozen_time.tick(timedelta(seconds=2.5))

                # Should now be unhealthy
                async with ClientSession() as session:
                    async with session.get("http://localhost:18001/healthz") as response:
                        assert response.status == 503

    async def test_heartbeat_resets_idle_time(self):
        """Test that heartbeats reset the idle timer."""

        tracker = LivenessTracker()
        async with create_server(tracker):
            # Start with old activity
            tracker._last_activity_time = time.time() - 5.0
            tracker._last_workflow_time = time.time() - 5.0

            # Should be unhealthy
            async with ClientSession() as session:
                async with session.get("http://localhost:18001/healthz") as response:
                    assert response.status == 503

            # Record heartbeat
            tracker.record_heartbeat()

            # Should now be healthy again
            async with ClientSession() as session:
                async with session.get("http://localhost:18001/healthz") as response:
                    assert response.status == 200
                    data = await response.json()
                    assert data["idle_seconds"] < 1.0

    async def test_different_max_idle_thresholds(self):
        """Test that different max_idle_seconds values work correctly."""

        tracker = LivenessTracker()
        # Create server with very short threshold
        server = HealthCheckServer(port=18004, liveness_tracker=tracker, max_idle_seconds=0.5)
        await server.start()

        try:
            tracker.record_activity_execution()
            await asyncio.sleep(0.7)

            async with ClientSession() as session:
                async with session.get("http://localhost:18004/healthz") as response:
                    assert response.status == 503
                    data = await response.json()
                    assert data["max_idle_seconds"] == 0.5
        finally:
            await server.stop()
