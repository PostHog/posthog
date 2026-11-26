import json
from queue import Empty

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from celery.schedules import crontab
from kombu import Connection
from parameterized import parameterized

from posthog.celery import app
from posthog.tasks.scheduled import instance_spread_minute, setup_periodic_tasks
from posthog.tasks.tasks import send_delayed_org_usage_reports
from posthog.tasks.team_llm_gateway_quota import reconcile_llm_gateway_quota_projection


class TestScheduledTasks(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(app.conf.update, task_always_eager=app.conf.task_always_eager)
        app.conf.update(task_always_eager=False)

    @parameterized.expand(
        [
            ("daily", "US", "send instance usage report", False),
            ("delayed_eu", "EU", "send delayed org usage reports", False),
            ("delayed_us", "US", "send delayed org usage reports", False),
            ("delayed_json", "EU", "send delayed org usage reports", True),
        ]
    )
    def test_usage_report_schedule_publishes_organization_filter(
        self, _name: str, region: str, schedule_name: str, json_payload: bool
    ) -> None:
        organization_ids = {
            "EU": ["00000000-0000-0000-0000-000000000001"],
            "US": ["00000000-0000-0000-0000-000000000002"],
        }
        sender = MagicMock()
        with (
            self.settings(CLOUD_DEPLOYMENT=region),
            patch(
                "posthog.tasks.tasks.posthoganalytics.get_feature_flag_payload",
                return_value=None,
            ) as flag_payload,
            Connection("memory://") as connection,
        ):
            setup_periodic_tasks(sender)
            flag_payload.return_value = json.dumps(organization_ids) if json_payload else organization_ids
            signature = next(
                call.args[1]
                for call in sender.add_periodic_task.call_args_list
                if call.kwargs.get("name") == schedule_name
            )
            with patch.object(app, "producer_or_acquire", return_value=connection.Producer()):
                signature.apply(throw=True)
            with connection.SimpleQueue("usage_reports") as queue:
                message = queue.get(block=False)
                message.ack()
                assert message.headers["task"] == "posthog.tasks.usage_report.send_all_org_usage_reports"
                expected = None if schedule_name == "send instance usage report" else organization_ids[region]
                assert message.payload[1].get("organization_ids") == expected

    @parameterized.expand(
        [
            ("unavailable", None),
            ("empty_payload", {}),
            ("empty_list", {"EU": []}),
            ("other_region_only", {"US": ["00000000-0000-0000-0000-000000000001"]}),
            ("invalid_json", "not json"),
            ("invalid_payload", []),
            ("invalid_list", {"EU": "00000000-0000-0000-0000-000000000001"}),
            ("empty_id", {"EU": [""]}),
            ("invalid_id_type", {"EU": [None]}),
        ]
    )
    def test_delayed_usage_report_does_not_publish_without_valid_organizations(
        self, _name: str, payload: object
    ) -> None:
        with (
            self.settings(CLOUD_DEPLOYMENT="EU"),
            patch("posthog.tasks.tasks.posthoganalytics.get_feature_flag_payload", return_value=payload),
            Connection("memory://") as connection,
            patch.object(app, "producer_or_acquire", return_value=connection.Producer()),
        ):
            send_delayed_org_usage_reports.apply(throw=True)
            with connection.SimpleQueue("usage_reports") as queue:
                with self.assertRaises(Empty):
                    queue.get(block=False)

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
