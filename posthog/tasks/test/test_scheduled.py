from django.test import SimpleTestCase, TestCase

from posthog.celery import app
from posthog.tasks.scheduled import instance_spread_minute, setup_periodic_tasks


class TestScheduledTasks(TestCase):
    def test_scheduled_tasks(self) -> None:
        """
        `setup_periodic_tasks` may fail silently. This test ensures that it doesn't.
        """
        try:
            setup_periodic_tasks(app)
        except Exception as exc:
            assert exc is None, exc


class TestInstanceSpreadMinute(SimpleTestCase):
    def test_one_installation_keeps_its_minute_in_every_process(self) -> None:
        # A literal, because the minute has to survive a beat restart. A hash that
        # is only stable inside one process, such as the built-in hash(), passes an
        # equality check between two calls and still moves the schedule on restart.
        with self.settings(SITE_URL="https://an-installation.example.com"):
            assert instance_spread_minute("send license usage", 40) == "18"

    def test_installations_do_not_all_get_the_same_minute(self) -> None:
        minutes = set()
        for site_url in ("site-one", "site-two", "site-three", "site-four"):
            with self.settings(SITE_URL=site_url):
                minutes.add(instance_spread_minute("send license usage", 40))
        assert len(minutes) > 1
