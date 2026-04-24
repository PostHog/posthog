from datetime import datetime, timedelta
from typing import ClassVar, Optional

from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from parameterized import parameterized
from prometheus_client import CollectorRegistry

from posthog.models import Organization, Team
from posthog.tasks.tasks import capture_task_run_state_metrics

from products.tasks.backend.models import Task, TaskRun


class TestCaptureTaskRunStateMetrics(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]

    @classmethod
    def setUpTestData(cls) -> None:
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")

    def _make_task_run(
        self,
        *,
        origin: Task.OriginProduct,
        status: TaskRun.Status,
        environment: TaskRun.Environment = TaskRun.Environment.CLOUD,
        created_at: Optional[datetime] = None,
    ) -> TaskRun:
        task = Task.objects.create(
            team=self.team,
            title="t",
            description="d",
            origin_product=origin,
        )
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=status,
            environment=environment,
        )
        if created_at is not None:
            TaskRun.objects.filter(pk=run.pk).update(created_at=created_at)
            run.refresh_from_db()
        return run

    def _run_with_registry(self) -> CollectorRegistry:
        registry = CollectorRegistry()
        context = MagicMock()
        context.__enter__ = MagicMock(return_value=registry)
        context.__exit__ = MagicMock(return_value=False)
        with patch("posthog.tasks.tasks.pushed_metrics_registry", return_value=context):
            capture_task_run_state_metrics()
        return registry

    def test_emits_counts_grouped_by_status_origin_and_environment(self) -> None:
        self._make_task_run(origin=Task.OriginProduct.SLACK, status=TaskRun.Status.QUEUED)
        self._make_task_run(origin=Task.OriginProduct.SLACK, status=TaskRun.Status.QUEUED)
        self._make_task_run(origin=Task.OriginProduct.USER_CREATED, status=TaskRun.Status.IN_PROGRESS)
        self._make_task_run(
            origin=Task.OriginProduct.USER_CREATED,
            status=TaskRun.Status.IN_PROGRESS,
            environment=TaskRun.Environment.LOCAL,
        )

        registry = self._run_with_registry()

        assert (
            registry.get_sample_value(
                "posthog_tasks_runs_in_status",
                {"status": "queued", "origin_product": "slack", "environment": "cloud"},
            )
            == 2
        )
        assert (
            registry.get_sample_value(
                "posthog_tasks_runs_in_status",
                {"status": "in_progress", "origin_product": "user_created", "environment": "cloud"},
            )
            == 1
        )
        assert (
            registry.get_sample_value(
                "posthog_tasks_runs_in_status",
                {"status": "in_progress", "origin_product": "user_created", "environment": "local"},
            )
            == 1
        )

    @parameterized.expand(
        [
            (TaskRun.Status.COMPLETED,),
            (TaskRun.Status.FAILED,),
            (TaskRun.Status.CANCELLED,),
        ]
    )
    def test_ignores_terminal_statuses(self, status: TaskRun.Status) -> None:
        self._make_task_run(origin=Task.OriginProduct.SLACK, status=status)

        registry = self._run_with_registry()

        assert (
            registry.get_sample_value(
                "posthog_tasks_runs_in_status",
                {"status": status.value, "origin_product": "slack", "environment": "cloud"},
            )
            is None
        )

    def test_emits_oldest_open_run_age(self) -> None:
        long_ago = timezone.now() - timedelta(minutes=30)
        self._make_task_run(
            origin=Task.OriginProduct.SLACK,
            status=TaskRun.Status.QUEUED,
            created_at=long_ago,
        )
        self._make_task_run(origin=Task.OriginProduct.SLACK, status=TaskRun.Status.QUEUED)

        registry = self._run_with_registry()

        age = registry.get_sample_value(
            "posthog_tasks_oldest_open_run_age_seconds",
            {"status": "queued", "origin_product": "slack", "environment": "cloud"},
        )
        assert age is not None
        # Oldest run was ~30 minutes ago; allow generous slack for test timing.
        assert 1500 < age < 2400

    def test_emits_runs_created_1h_by_origin_and_environment(self) -> None:
        # Two Slack runs created just now, one old run (outside the 1h window), one PostHog-code run.
        self._make_task_run(origin=Task.OriginProduct.SLACK, status=TaskRun.Status.QUEUED)
        self._make_task_run(origin=Task.OriginProduct.SLACK, status=TaskRun.Status.COMPLETED)
        self._make_task_run(
            origin=Task.OriginProduct.SLACK,
            status=TaskRun.Status.COMPLETED,
            created_at=timezone.now() - timedelta(hours=2),
        )
        self._make_task_run(origin=Task.OriginProduct.USER_CREATED, status=TaskRun.Status.COMPLETED)

        registry = self._run_with_registry()

        assert (
            registry.get_sample_value(
                "posthog_tasks_runs_created_1h",
                {"origin_product": "slack", "environment": "cloud"},
            )
            == 2
        )
        assert (
            registry.get_sample_value(
                "posthog_tasks_runs_created_1h",
                {"origin_product": "user_created", "environment": "cloud"},
            )
            == 1
        )

    def test_emits_runs_terminal_1h_grouped_by_status_and_origin(self) -> None:
        # 2 completed Slack runs + 1 failed User run in the last hour, plus 1 old completed run (outside 1h).
        self._make_task_run(origin=Task.OriginProduct.SLACK, status=TaskRun.Status.COMPLETED)
        self._make_task_run(origin=Task.OriginProduct.SLACK, status=TaskRun.Status.COMPLETED)
        self._make_task_run(origin=Task.OriginProduct.USER_CREATED, status=TaskRun.Status.FAILED)
        old = self._make_task_run(origin=Task.OriginProduct.SLACK, status=TaskRun.Status.COMPLETED)
        TaskRun.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timedelta(hours=2))

        registry = self._run_with_registry()

        assert (
            registry.get_sample_value(
                "posthog_tasks_runs_terminal_1h",
                {"status": "completed", "origin_product": "slack", "environment": "cloud"},
            )
            == 2
        )
        assert (
            registry.get_sample_value(
                "posthog_tasks_runs_terminal_1h",
                {"status": "failed", "origin_product": "user_created", "environment": "cloud"},
            )
            == 1
        )

    def test_age_gauge_only_covers_queued_and_in_progress(self) -> None:
        self._make_task_run(
            origin=Task.OriginProduct.SLACK,
            status=TaskRun.Status.NOT_STARTED,
            created_at=timezone.now() - timedelta(minutes=5),
        )

        registry = self._run_with_registry()

        assert (
            registry.get_sample_value(
                "posthog_tasks_oldest_open_run_age_seconds",
                {"status": "not_started", "origin_product": "slack", "environment": "cloud"},
            )
            is None
        )
        # But it should still appear in the count gauge (not_started is "open").
        assert (
            registry.get_sample_value(
                "posthog_tasks_runs_in_status",
                {"status": "not_started", "origin_product": "slack", "environment": "cloud"},
            )
            == 1
        )
