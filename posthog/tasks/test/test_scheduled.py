from django.test import TestCase

from redbeat.schedulers import RedBeatConfig

from posthog.celery import app
from posthog.tasks.scheduled import setup_periodic_tasks


class TestScheduledTasks(TestCase):
    def test_scheduled_tasks(self) -> None:
        """
        `setup_periodic_tasks` may fail silently. This test ensures that it doesn't.
        """
        try:
            setup_periodic_tasks(app)
        except Exception as exc:
            assert exc is None, exc

    def test_beat_startup_survives_transient_redis_outage(self) -> None:
        # RedBeatScheduler.setup_schedule hits Redis before the beat loop starts. Without these
        # retry settings a momentary Redis blip during a deploy crashes the beat process instead
        # of it waiting and reconnecting.
        assert app.conf.broker_connection_retry_on_startup is True
        # redbeat wraps its connection in a retrying proxy only when retry_period is configured
        assert RedBeatConfig(app).redbeat_redis_options.get("retry_period") == 60
