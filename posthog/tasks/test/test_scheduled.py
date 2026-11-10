from unittest.mock import MagicMock

from django.test import SimpleTestCase

from celery.schedules import crontab
from parameterized import parameterized

from posthog.celery import app
from posthog.tasks.scheduled import instance_spread_minute, setup_periodic_tasks
from posthog.tasks.team_llm_gateway_quota import reconcile_llm_gateway_quota_projection


class TestScheduledTasks(SimpleTestCase):
    def test_spend_recovery_runs_every_ten_minutes_and_expires_before_the_next_sweep(self) -> None:
        sender = MagicMock()
        setup_periodic_tasks(sender)
        calls = [
            call
            for call in sender.add_periodic_task.call_args_list
            if call.kwargs.get("name") == "recover signals spend"
        ]
        assert len(calls) == 1
        assert calls[0].args[0].minute == {0, 10, 20, 30, 40, 50}
        assert calls[0].kwargs["expires"] == 10 * 60

    def test_scheduled_tasks(self) -> None:
        """
        `setup_periodic_tasks` may fail silently. This test ensures that it doesn't.
        """
        try:
            setup_periodic_tasks(app)
        except Exception as exc:
            assert exc is None, exc


class TestCrontabSchedules(SimpleTestCase):
    @parameterized.expand([("cloud", "US"), ("hobby", None)])
    def test_a_schedule_limited_to_some_hours_also_sets_a_minute(self, _name: str, deployment: str | None) -> None:
        sender = MagicMock()
        with self.settings(CLOUD_DEPLOYMENT=deployment, DEBUG=False):
            setup_periodic_tasks(sender)
        every_minute_of_some_hours = [
            call.kwargs.get("name")
            for call in sender.add_periodic_task.call_args_list
            if isinstance(call.args[0], crontab) and len(call.args[0].hour) < 24 and len(call.args[0].minute) == 60
        ]
        self.assertEqual(every_minute_of_some_hours, [])


class TestPrivacyTaskScheduling(SimpleTestCase):
    @parameterized.expand([("disabled", "", 0), ("enabled", "test-table", 1)])
    def test_privacy_schedule_requires_configured_worker(self, _name: str, table: str, expected_count: int) -> None:
        sender = MagicMock()
        with self.settings(AI_RESEARCH_REPLAY_KEY_TABLE=table):
            setup_periodic_tasks(sender)
        calls = [
            call
            for call in sender.add_periodic_task.call_args_list
            if call.kwargs.get("name") == "process-ai-training-privacy"
        ]
        self.assertEqual(len(calls), expected_count)
        if calls:
            self.assertEqual(calls[0].args[1].type.queue, "ai_research_privacy")


class TestLLMGatewayQuotaReconcileScheduling(SimpleTestCase):
    def test_the_reconcile_runs_every_15_minutes(self) -> None:
        sender = MagicMock()
        with self.settings(CLOUD_DEPLOYMENT="US"):
            setup_periodic_tasks(sender)
        calls = [
            call
            for call in sender.add_periodic_task.call_args_list
            if call.kwargs.get("name") == "llm-gateway quota projection reconcile"
        ]
        self.assertEqual(len(calls), 1)
        schedule, signature = calls[0].args
        self.assertEqual(schedule.minute, {7, 22, 37, 52})
        self.assertEqual(signature.task, reconcile_llm_gateway_quota_projection.name)


class TestHobbySchedule(SimpleTestCase):
    @parameterized.expand(
        [
            ("hobby", None, {"10 sec heartbeat": 60, "query performance heartbeat": 20}),
            ("cloud", "US", {"10 sec heartbeat": 10, "query performance heartbeat": 20}),
        ]
    )
    def test_hobby_keeps_slower_heartbeats(self, _name: str, deployment: str | None, expected: dict[str, int]) -> None:
        sender = MagicMock()
        with self.settings(CLOUD_DEPLOYMENT=deployment, DEBUG=False):
            setup_periodic_tasks(sender)
        scheduled = {call.kwargs.get("name"): call.args[0] for call in sender.add_periodic_task.call_args_list}
        self.assertEqual(
            {
                name: scheduled[name]
                for name in ("10 sec heartbeat", "query performance heartbeat")
                if name in scheduled
            },
            expected,
        )


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


class TestSignalsRatedUsageScheduling(SimpleTestCase):
    @parameterized.expand([("self_hosted", None, 0), ("cloud", "US", 1)])
    def test_rated_usage_runs_daily_in_cloud(self, _name: str, deployment: str | None, expected_count: int) -> None:
        sender = MagicMock()
        with self.settings(CLOUD_DEPLOYMENT=deployment):
            setup_periodic_tasks(sender)
        calls = [
            call
            for call in sender.add_periodic_task.call_args_list
            if call.kwargs.get("name") == "report self-driving rated usage"
        ]
        assert len(calls) == expected_count
        if calls:
            schedule, signature = calls[0].args
            assert schedule.hour == {3}
            assert schedule.minute == {17}
            assert signature.type.name == "products.signals.backend.rated_usage_tasks.enqueue_signals_rated_usage"
            assert signature.type.queue == "usage_reports"
