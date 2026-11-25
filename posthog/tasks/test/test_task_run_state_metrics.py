from datetime import datetime, timedelta
from typing import TYPE_CHECKING, ClassVar, Optional

from unittest.mock import AsyncMock, MagicMock, patch

from django.apps import apps
from django.db import OperationalError, ProgrammingError
from django.test import TestCase, override_settings
from django.utils import timezone

import requests_mock
from parameterized import parameterized
from prometheus_client import CollectorRegistry
from temporalio.service import RPCError, RPCStatusCode

from posthog.models import Organization, Team
from posthog.tasks.tasks import capture_task_run_state_metrics, capture_task_status_shadow_metrics

if TYPE_CHECKING:
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
        origin: "Task.OriginProduct",
        status: "TaskRun.Status",
        environment: "Optional[TaskRun.Environment]" = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        queued_at: Optional[datetime] = None,
    ) -> "TaskRun":
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        if environment is None:
            environment = TaskRun.Environment.CLOUD
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
        # .update() bypasses auto_now, so an explicit updated_at sticks.
        overrides = {
            field: value
            for field, value in (("created_at", created_at), ("updated_at", updated_at), ("queued_at", queued_at))
            if value is not None
        }
        if overrides:
            TaskRun.objects.filter(pk=run.pk).update(**overrides)
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
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
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
                {"status": "queued", "origin_product": "slack", "run_environment": "cloud"},
            )
            == 2
        )
        assert (
            registry.get_sample_value(
                "posthog_tasks_runs_in_status",
                {"status": "in_progress", "origin_product": "user_created", "run_environment": "cloud"},
            )
            == 1
        )
        assert (
            registry.get_sample_value(
                "posthog_tasks_runs_in_status",
                {"status": "in_progress", "origin_product": "user_created", "run_environment": "local"},
            )
            == 1
        )

    @parameterized.expand(
        [
            (apps.get_model("tasks", "TaskRun").Status.COMPLETED,),
            (apps.get_model("tasks", "TaskRun").Status.FAILED,),
            (apps.get_model("tasks", "TaskRun").Status.CANCELLED,),
        ]
    )
    def test_ignores_terminal_statuses(self, status: "TaskRun.Status") -> None:
        Task = apps.get_model("tasks", "Task")
        self._make_task_run(origin=Task.OriginProduct.SLACK, status=status)

        registry = self._run_with_registry()

        assert (
            registry.get_sample_value(
                "posthog_tasks_runs_in_status",
                {"status": status.value, "origin_product": "slack", "run_environment": "cloud"},
            )
            is None
        )

    def test_emits_oldest_open_run_age(self) -> None:
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
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
            {"status": "queued", "origin_product": "slack", "run_environment": "cloud"},
        )
        assert age is not None
        # Oldest run was ~30 minutes ago; allow generous slack for test timing.
        assert 1500 < age < 2400

    @parameterized.expand(
        [
            # A cloud handoff re-queues an existing run without resetting created_at, so anchoring
            # the queue wait on created_at would report the whole pre-handoff lifetime as backlog.
            ("requeued_by_handoff", apps.get_model("tasks", "TaskRun").Status.QUEUED, 30, 1500, 2400),
            # An unrelated write to a still-queued run advances updated_at, so anchoring on
            # updated_at would make a genuinely stranded run look newly queued.
            ("written_while_still_queued", apps.get_model("tasks", "TaskRun").Status.QUEUED, 360, 20000, 23000),
            # Rows queued before queued_at existed fall back to created_at.
            ("queued_before_the_field_existed", apps.get_model("tasks", "TaskRun").Status.QUEUED, None, 20000, 23000),
            ("in_progress_reports_lifetime", apps.get_model("tasks", "TaskRun").Status.IN_PROGRESS, 30, 20000, 23000),
        ]
    )
    def test_oldest_age_anchors_queued_runs_on_queued_at(
        self, _name: str, status: "TaskRun.Status", queued_minutes_ago: Optional[int], low: int, high: int
    ) -> None:
        Task = apps.get_model("tasks", "Task")
        now = timezone.now()
        self._make_task_run(
            origin=Task.OriginProduct.SLACK,
            status=status,
            created_at=now - timedelta(hours=6),
            updated_at=now - timedelta(minutes=30),
            queued_at=None if queued_minutes_ago is None else now - timedelta(minutes=queued_minutes_ago),
        )

        registry = self._run_with_registry()

        age = registry.get_sample_value(
            "posthog_tasks_oldest_open_run_age_seconds",
            {"status": status.value, "origin_product": "slack", "run_environment": "cloud"},
        )
        assert age is not None
        assert low < age < high

    def test_emits_runs_created_1h_by_origin_and_environment(self) -> None:
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
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
                {"origin_product": "slack", "run_environment": "cloud"},
            )
            == 2
        )
        assert (
            registry.get_sample_value(
                "posthog_tasks_runs_created_1h",
                {"origin_product": "user_created", "run_environment": "cloud"},
            )
            == 1
        )

    def test_emits_runs_terminal_1h_grouped_by_status_and_origin(self) -> None:
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        # 2 completed Slack runs + 1 failed User run in the last hour, plus 2 old completed runs (outside 1h).
        self._make_task_run(origin=Task.OriginProduct.SLACK, status=TaskRun.Status.COMPLETED)
        self._make_task_run(origin=Task.OriginProduct.SLACK, status=TaskRun.Status.COMPLETED)
        self._make_task_run(origin=Task.OriginProduct.USER_CREATED, status=TaskRun.Status.FAILED)
        old = self._make_task_run(origin=Task.OriginProduct.SLACK, status=TaskRun.Status.COMPLETED)
        TaskRun.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timedelta(hours=2))
        touched = self._make_task_run(origin=Task.OriginProduct.SLACK, status=TaskRun.Status.COMPLETED)
        TaskRun.objects.filter(pk=touched.pk).update(completed_at=timezone.now() - timedelta(hours=2))

        registry = self._run_with_registry()

        assert (
            registry.get_sample_value(
                "posthog_tasks_runs_terminal_1h",
                {"status": "completed", "origin_product": "slack", "run_environment": "cloud"},
            )
            == 2
        )
        assert (
            registry.get_sample_value(
                "posthog_tasks_runs_terminal_1h",
                {"status": "failed", "origin_product": "user_created", "run_environment": "cloud"},
            )
            == 1
        )

    @parameterized.expand(
        [
            ("missing_table", ProgrammingError('relation "posthog_task_run" does not exist')),
            ("transient_connection_timeout", OperationalError("connection timeout expired")),
        ]
    )
    def test_transient_db_errors_are_suppressed_without_reporting(self, _name: str, error: Exception) -> None:
        with (
            patch(
                "products.tasks.backend.facade.api.collect_task_run_state_metrics",
                side_effect=error,
            ),
            patch("posthog.tasks.tasks.capture_exception") as capture_mock,
        ):
            self._run_with_registry()

        capture_mock.assert_not_called()

    def test_unexpected_errors_are_still_reported(self) -> None:
        with (
            patch(
                "products.tasks.backend.facade.api.collect_task_run_state_metrics",
                side_effect=ValueError("boom"),
            ),
            patch("posthog.tasks.tasks.capture_exception") as capture_mock,
        ):
            self._run_with_registry()

        capture_mock.assert_called_once()

    def test_age_gauge_only_covers_queued_and_in_progress(self) -> None:
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        self._make_task_run(
            origin=Task.OriginProduct.SLACK,
            status=TaskRun.Status.NOT_STARTED,
            created_at=timezone.now() - timedelta(minutes=5),
        )

        registry = self._run_with_registry()

        assert (
            registry.get_sample_value(
                "posthog_tasks_oldest_open_run_age_seconds",
                {"status": "not_started", "origin_product": "slack", "run_environment": "cloud"},
            )
            is None
        )
        # But it should still appear in the count gauge (not_started is "open").
        assert (
            registry.get_sample_value(
                "posthog_tasks_runs_in_status",
                {"status": "not_started", "origin_product": "slack", "run_environment": "cloud"},
            )
            == 1
        )


class TestCaptureTaskStatusShadowMetrics(TestCase):
    def test_reports_the_drift_it_found_and_the_repairs_it_made(self) -> None:
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        organization = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=organization, name="Test Team")
        task = Task.objects.create(team=team, title="t", description="d", origin_product=Task.OriginProduct.SLACK)
        TaskRun.objects.create(
            task=task, team=team, status=TaskRun.Status.IN_PROGRESS, created_at=timezone.now() - timedelta(hours=3)
        )
        TaskRun.objects.filter(task=task).update(updated_at=timezone.now() - timedelta(hours=3))
        Task.objects.filter(pk=task.pk).update(status=Task.Status.QUEUED)
        registry = CollectorRegistry()
        context = MagicMock()
        context.__enter__ = MagicMock(return_value=registry)
        context.__exit__ = MagicMock(return_value=False)

        with patch("posthog.tasks.tasks.pushed_metrics_registry", return_value=context):
            capture_task_status_shadow_metrics()

        labels = {"stored_status": "queued", "derived_status": "running"}
        assert registry.get_sample_value("posthog_tasks_status_shadow_mismatches", labels) == 1
        assert registry.get_sample_value("posthog_tasks_status_shadow_repaired", labels) == 1
        stale_labels = {"profile": "none", "run_environment": "cloud", "rule": "heartbeat"}
        assert registry.get_sample_value("posthog_tasks_stale_live_runs", stale_labels) == 1
        task.refresh_from_db()
        assert task.status == Task.Status.RUNNING

    def test_ends_a_quiet_run_of_a_profile_the_sweep_enforces(self) -> None:
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        organization = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=organization, name="Test Team")
        task = Task.objects.create(
            team=team, title="t", description="d", origin_product=Task.OriginProduct.USER_CREATED, profile="user"
        )
        run = TaskRun.objects.create(
            task=task, team=team, status=TaskRun.Status.IN_PROGRESS, created_at=timezone.now() - timedelta(hours=3)
        )
        TaskRun.objects.filter(pk=run.pk).update(updated_at=timezone.now() - timedelta(hours=3))
        registry = CollectorRegistry()
        context = MagicMock()
        context.__enter__ = MagicMock(return_value=registry)
        context.__exit__ = MagicMock(return_value=False)

        with (
            patch("posthog.tasks.tasks.pushed_metrics_registry", return_value=context),
            patch(
                "products.tasks.backend.stale_runs.posthoganalytics.get_feature_flag_payload",
                return_value={"user": "enforce"},
            ),
            patch("posthog.temporal.common.client.sync_connect") as connect,
        ):
            connect.return_value.get_workflow_handle.return_value.describe = AsyncMock(
                side_effect=RPCError("workflow not found", RPCStatusCode.NOT_FOUND, b"")
            )
            capture_task_status_shadow_metrics()

        run.refresh_from_db()
        assert run.status == TaskRun.Status.FAILED
        assert registry.get_sample_value("posthog_tasks_stale_live_runs_swept", {"profile": "user"}) == 1

    @override_settings(
        SANDBOX_AI_GATEWAY_URL="https://gateway.example.com",
        SANDBOX_AI_GATEWAY_WORKER_URL="http://localhost:18080",
        SANDBOX_AI_GATEWAY_MINT_KEY="phs_test",
    )
    def test_revokes_the_gateway_tokens_of_a_run_that_ended(self) -> None:
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        organization = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=organization, name="Test Team")
        task = Task.objects.create(
            team=team, title="t", description="d", origin_product=Task.OriginProduct.USER_CREATED, profile="user"
        )
        run = TaskRun.objects.create(
            task=task,
            team=team,
            status=TaskRun.Status.COMPLETED,
            completed_at=timezone.now(),
            state={"gateway_token_hashes": ["a" * 64]},
        )
        registry = CollectorRegistry()
        context = MagicMock()
        context.__enter__ = MagicMock(return_value=registry)
        context.__exit__ = MagicMock(return_value=False)

        with (
            patch("posthog.tasks.tasks.pushed_metrics_registry", return_value=context),
            patch(
                "products.tasks.backend.stale_runs.posthoganalytics.get_feature_flag_payload",
                return_value={"user": "enforce"},
            ),
            requests_mock.Mocker() as gateway,
        ):
            gateway.post("http://localhost:18080/v1/tokens/revoke", status_code=200)
            capture_task_status_shadow_metrics()

        run.refresh_from_db()
        assert "gateway_token_hashes" not in run.state
        labels = {"profile": "user", "outcome": "revoked"}
        assert registry.get_sample_value("posthog_tasks_ended_run_gateway_tokens", labels) == 1
