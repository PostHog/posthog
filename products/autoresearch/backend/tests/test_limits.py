from datetime import timedelta
from unittest.mock import patch
from django.utils import timezone as django_timezone

from posthog.test.base import BaseTest
from products.autoresearch.backend.limits import (
    AutoresearchLimits,
    AutoresearchLimitsReport,
    DailyTrainingCapExceeded,
    LivePipelineCapExceeded,
    enforce_live_pipelines_cap,
    enforce_team_training_daily_cap,
    get_team_limits_report,
    resolve_autoresearch_limits,
)
from products.autoresearch.backend.models import (
    AutoresearchPipeline,
    AutoresearchTrainingRun,
)


class TestAutoresearchLimits(BaseTest):
    def setUp(self):
        super().setUp()
        self.pipeline = AutoresearchPipeline.objects.create(
            team=self.team,
            name="Test Pipeline",
            target_event="$pageview",
            created_by=self.user,
        )

    def test_resolve_autoresearch_limits_defaults(self):
        with patch("products.autoresearch.backend.limits.read_flag_payload", return_value=None):
            limits = resolve_autoresearch_limits(self.team.id)
            assert limits == AutoresearchLimits(
                max_training_runs_per_day=3,
                max_iterations_per_run=10,
                max_live_pipelines=3,
            )

    def test_resolve_autoresearch_limits_default_team_config_override(self):
        payload = {
            "default_team_config": {
                "max_training_runs_per_day": 5,
                "max_iterations_per_run": 20,
                "max_live_pipelines": 5,
            }
        }
        with patch("products.autoresearch.backend.limits.read_flag_payload", return_value=payload):
            limits = resolve_autoresearch_limits(self.team.id)
            assert limits.max_training_runs_per_day == 5
            assert limits.max_iterations_per_run == 20
            assert limits.max_live_pipelines == 5

    def test_resolve_autoresearch_limits_team_specific_override(self):
        payload = {
            "default_team_config": {
                "max_training_runs_per_day": 5,
                "max_iterations_per_run": 20,
                "max_live_pipelines": 5,
            },
            "team_configs": {
                str(self.team.id): {
                    "max_training_runs_per_day": 10,
                    "max_iterations_per_run": 30,
                    "max_live_pipelines": 2,
                }
            },
        }
        with patch("products.autoresearch.backend.limits.read_flag_payload", return_value=payload):
            limits = resolve_autoresearch_limits(self.team.id)
            assert limits.max_training_runs_per_day == 10
            assert limits.max_iterations_per_run == 30
            assert limits.max_live_pipelines == 2

            # Other team falls back to default_team_config
            other_team_limits = resolve_autoresearch_limits(self.team.id + 999)
            assert other_team_limits.max_training_runs_per_day == 5
            assert other_team_limits.max_iterations_per_run == 20
            assert other_team_limits.max_live_pipelines == 5

    def test_enforce_team_training_daily_cap_allows_when_under_limit(self):
        with patch("products.autoresearch.backend.limits.read_flag_payload", return_value=None):
            allowed, used, limit, next_slot = enforce_team_training_daily_cap(self.team.id, raise_error=False)
            assert allowed is True
            assert used == 0
            assert limit == 3
            assert next_slot is None

    def test_enforce_team_training_daily_cap_counts_recent_internal_runs(self):
        now = django_timezone.now()
        # 2 recent runs with task_id or agent_runtime_adapter
        AutoresearchTrainingRun.objects.create(
            pipeline=self.pipeline,
            status=AutoresearchTrainingRun.Status.COMPLETED,
            iteration_budget=5,
            task_id="task_1",
            agent_runtime_adapter="test_adapter",
            created_at=now - timedelta(hours=2),
        )
        AutoresearchTrainingRun.objects.create(
            pipeline=self.pipeline,
            status=AutoresearchTrainingRun.Status.RUNNING,
            iteration_budget=5,
            agent_runtime_adapter="test_adapter",
            created_at=now - timedelta(hours=1),
        )

        with patch("products.autoresearch.backend.limits.read_flag_payload", return_value=None):
            allowed, used, limit, next_slot = enforce_team_training_daily_cap(self.team.id, raise_error=False)
            assert allowed is True
            assert used == 2
            assert limit == 3

    def test_enforce_team_training_daily_cap_blocks_when_cap_reached(self):
        now = django_timezone.now()
        # Create 3 runs within the last 24 hours
        oldest_run_time = now - timedelta(hours=10)
        AutoresearchTrainingRun.objects.create(
            pipeline=self.pipeline,
            status=AutoresearchTrainingRun.Status.COMPLETED,
            iteration_budget=5,
            task_id="task_1",
            agent_runtime_adapter="adapter",
            created_at=oldest_run_time,
        )
        AutoresearchTrainingRun.objects.create(
            pipeline=self.pipeline,
            status=AutoresearchTrainingRun.Status.COMPLETED,
            iteration_budget=5,
            task_id="task_2",
            agent_runtime_adapter="adapter",
            created_at=now - timedelta(hours=5),
        )
        AutoresearchTrainingRun.objects.create(
            pipeline=self.pipeline,
            status=AutoresearchTrainingRun.Status.RUNNING,
            iteration_budget=5,
            task_id="task_3",
            agent_runtime_adapter="adapter",
            created_at=now - timedelta(hours=1),
        )

        with patch("products.autoresearch.backend.limits.read_flag_payload", return_value=None):
            allowed, used, limit, next_slot = enforce_team_training_daily_cap(self.team.id, raise_error=False)
            assert allowed is False
            assert used == 3
            assert limit == 3
            assert next_slot is not None
            # Oldest run created_at + 24 hours
            expected_slot = oldest_run_time + timedelta(hours=24)
            assert abs((next_slot - expected_slot).total_seconds()) < 2

            # When raise_error=True, raises DailyTrainingCapExceeded
            try:
                enforce_team_training_daily_cap(self.team.id, raise_error=True)
                assert False, "Expected DailyTrainingCapExceeded"
            except DailyTrainingCapExceeded as exc:
                assert exc.team_id == self.team.id
                assert exc.runs_used == 3
                assert exc.limit == 3
                assert exc.next_slot_opens_at == next_slot

    def test_enforce_team_training_daily_cap_ignores_runs_older_than_24h(self):
        now = django_timezone.now()
        # 3 runs older than 24h
        for i in range(3):
            AutoresearchTrainingRun.objects.create(
                pipeline=self.pipeline,
                status=AutoresearchTrainingRun.Status.COMPLETED,
                iteration_budget=5,
                task_id=f"old_task_{i}",
                agent_runtime_adapter="adapter",
                created_at=now - timedelta(hours=25 + i),
            )

        with patch("products.autoresearch.backend.limits.read_flag_payload", return_value=None):
            allowed, used, limit, next_slot = enforce_team_training_daily_cap(self.team.id, raise_error=False)
            assert allowed is True
            assert used == 0
            assert limit == 3

    def test_enforce_team_training_daily_cap_ignores_external_runs(self):
        now = django_timezone.now()
        # External runs have task_id=None and agent_runtime_adapter empty or None, status completed
        for _ in range(5):
            AutoresearchTrainingRun.objects.create(
                pipeline=self.pipeline,
                status=AutoresearchTrainingRun.Status.COMPLETED,
                iteration_budget=5,
                task_id=None,
                agent_runtime_adapter=None,
                created_at=now - timedelta(hours=1),
            )

        with patch("products.autoresearch.backend.limits.read_flag_payload", return_value=None):
            allowed, used, limit, next_slot = enforce_team_training_daily_cap(self.team.id, raise_error=False)
            assert allowed is True
            assert used == 0
            assert limit == 3

    # ──────────────────────────────────── live pipelines cap ─────────────────────────────────────

    def test_enforce_live_pipelines_cap_counts_only_active_statuses(self):
        # self.pipeline is currently DRAFT, so 0 live pipelines
        with patch("products.autoresearch.backend.limits.read_flag_payload", return_value=None):
            count, limit = enforce_live_pipelines_cap(self.team.id)
            assert count == 0
            assert limit == 3

        # Add 1 bootstrapping, 1 running, 1 converged
        AutoresearchPipeline.objects.create(
            team=self.team, name="Bootstrapping", status=AutoresearchPipeline.Status.BOOTSTRAPPING
        )
        AutoresearchPipeline.objects.create(
            team=self.team, name="Running", status=AutoresearchPipeline.Status.RUNNING
        )
        AutoresearchPipeline.objects.create(
            team=self.team, name="Converged", status=AutoresearchPipeline.Status.CONVERGED
        )

        # Add non-active pipelines: paused, archived, draft
        AutoresearchPipeline.objects.create(team=self.team, name="Paused", status=AutoresearchPipeline.Status.PAUSED)
        AutoresearchPipeline.objects.create(
            team=self.team, name="Archived", status=AutoresearchPipeline.Status.ARCHIVED
        )
        AutoresearchPipeline.objects.create(team=self.team, name="Draft", status=AutoresearchPipeline.Status.DRAFT)

        with patch("products.autoresearch.backend.limits.read_flag_payload", return_value=None):
            # Already at 3 live pipelines, next should raise LivePipelineCapExceeded
            try:
                enforce_live_pipelines_cap(self.team.id)
                assert False, "Expected LivePipelineCapExceeded"
            except LivePipelineCapExceeded as exc:
                assert exc.count == 3
                assert exc.limit == 3
                assert "This project already has 3 active models. Pause or archive one to start another." in str(exc)

    def test_enforce_live_pipelines_cap_flag_override(self):
        # Create 3 live pipelines
        for i in range(3):
            AutoresearchPipeline.objects.create(
                team=self.team, name=f"Live {i}", status=AutoresearchPipeline.Status.RUNNING
            )

        flag_payload = {
            "team_configs": {
                str(self.team.id): {
                    "max_live_pipelines": 5,
                }
            }
        }
        with patch("products.autoresearch.backend.limits.read_flag_payload", return_value=flag_payload):
            count, limit = enforce_live_pipelines_cap(self.team.id)
            assert count == 3
            assert limit == 5

    def test_get_team_limits_report(self):
        now = django_timezone.now()
        # 1 live pipeline
        self.pipeline.status = AutoresearchPipeline.Status.RUNNING
        self.pipeline.save(update_fields=["status"])

        # 1 run
        AutoresearchTrainingRun.objects.create(
            pipeline=self.pipeline,
            status=AutoresearchTrainingRun.Status.COMPLETED,
            iteration_budget=5,
            task_id="task_1",
            agent_runtime_adapter="adapter",
            created_at=now - timedelta(hours=2),
        )

        with patch("products.autoresearch.backend.limits.read_flag_payload", return_value=None):
            report = get_team_limits_report(self.team.id, now=now)
            assert report.max_training_runs_per_day == 3
            assert report.max_iterations_per_run == 10
            assert report.max_live_pipelines == 3
            assert report.training_runs_used_today == 1
            assert report.live_pipelines_count == 1
            assert report.next_training_slot_opens_at is None
            assert report.daily_training_cap_exceeded is False
            assert report.live_pipelines_cap_exceeded is False
