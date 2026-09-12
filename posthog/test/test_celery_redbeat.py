from unittest import TestCase
from unittest.mock import MagicMock, patch

from posthog.celery_redbeat import ResilientRedBeatScheduler


class TestResilientRedBeatScheduler(TestCase):
    def _make_scheduler(self) -> ResilientRedBeatScheduler:
        # Build an instance without running RedBeatScheduler.__init__ (which needs a live app/redis);
        # set only the attributes tick() touches.
        scheduler = ResilientRedBeatScheduler.__new__(ResilientRedBeatScheduler)
        scheduler.lock_key = "posthog:beat:lock"
        scheduler.lock = None
        scheduler.lock_timeout = 45
        scheduler.max_interval = 30
        scheduler.app = MagicMock()
        return scheduler

    @patch("posthog.celery_redbeat.RedBeatScheduler.tick")
    def test_tick_reacquires_lock_when_startup_acquisition_failed(self, mock_super_tick):
        # Reproduces the redbeat 2.3.3 race: beat_init swallowed the acquire() exception, so
        # lock_key is set but lock is None. The stock tick would deref None.extend and crash.
        scheduler = self._make_scheduler()
        mock_super_tick.return_value = 30

        acquired_lock = MagicMock()

        def fake_acquire() -> None:
            self.assertIsNone(scheduler.lock)  # acquisition happens before we hand off to super().tick
            scheduler.lock = acquired_lock

        with patch.object(scheduler, "_acquire_lock", side_effect=fake_acquire) as mock_acquire:
            result = scheduler.tick()

        mock_acquire.assert_called_once()
        self.assertIs(scheduler.lock, acquired_lock)
        mock_super_tick.assert_called_once()
        self.assertEqual(result, 30)

    @patch("posthog.celery_redbeat.RedBeatScheduler.tick")
    def test_tick_skips_without_crashing_when_reacquire_fails(self, mock_super_tick):
        # Redis still unhealthy on the tick: re-acquire fails, so skip the tick (return max_interval)
        # rather than letting the exception kill the single beat process.
        scheduler = self._make_scheduler()

        with patch.object(scheduler, "_acquire_lock", side_effect=ConnectionError("redis down")):
            result = scheduler.tick()

        self.assertEqual(result, scheduler.max_interval)
        mock_super_tick.assert_not_called()

    @patch("posthog.celery_redbeat.RedBeatScheduler.tick")
    def test_tick_does_not_reacquire_when_lock_present(self, mock_super_tick):
        scheduler = self._make_scheduler()
        scheduler.lock = MagicMock()
        mock_super_tick.return_value = 30

        with patch.object(scheduler, "_acquire_lock") as mock_acquire:
            result = scheduler.tick()

        mock_acquire.assert_not_called()
        mock_super_tick.assert_called_once()
        self.assertEqual(result, 30)
