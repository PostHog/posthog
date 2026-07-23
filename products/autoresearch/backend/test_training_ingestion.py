from posthog.test.base import BaseTest

from django.utils import timezone as django_timezone

from parameterized import parameterized

from products.autoresearch.backend.models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchTrainingRun,
)
from products.autoresearch.backend.training_ingestion import handle_task_run_completed


def _task_run(status: str = "completed", state: dict | None = None):
    """Build a minimal mock TaskRun-like object."""

    class FakeTaskRun:
        pass

    tr = FakeTaskRun()
    tr.id = "00000000-0000-0000-0000-000000000001"  # type: ignore[attr-defined]
    tr.status = status  # type: ignore[attr-defined]
    tr.state = state or {}  # type: ignore[attr-defined]
    tr.error_message = None  # type: ignore[attr-defined]
    return tr


class TestHandleTaskRunCompleted(BaseTest):
    def _make_pipeline(self, **kwargs) -> AutoresearchPipeline:
        defaults = {
            "team": self.team,
            "created_by": self.user,
            "name": "Test",
            "target_event": "$pageview",
            "horizon_days": 7,
            "iteration_budget": 10,
            "iteration_budget_remaining": 10,
        }
        defaults.update(kwargs)
        return AutoresearchPipeline.objects.create(**defaults)

    def _make_training_run(self, pipeline: AutoresearchPipeline, **kwargs) -> AutoresearchTrainingRun:
        defaults = {
            "pipeline": pipeline,
            "status": AutoresearchTrainingRun.Status.RUNNING,
            "iteration_budget": 10,
            "started_at": django_timezone.now(),
        }
        defaults.update(kwargs)
        return AutoresearchTrainingRun.objects.create(**defaults)

    def _record_iteration(self, training_run, *, number=0, status="kept", holdout=0.8) -> None:
        AutoresearchIteration.objects.create(
            training_run=training_run,
            pipeline=training_run.pipeline,
            iteration_number=number,
            recipe_hash=f"hash{number}",
            recipe_snapshot={"feature_sql": "SELECT person_id AS distinct_id FROM events"},
            model_spec={"model_class": "sklearn.linear_model.LogisticRegression", "model_params": {}},
            holdout_score=holdout,
            status=status,
            agent_description="test",
        )

    def test_skips_run_without_training_run_id(self) -> None:
        handle_task_run_completed(_task_run(state={}))
        assert AutoresearchTrainingRun.objects.count() == 0

    def test_skips_unknown_training_run_id(self) -> None:
        # A stale/unknown id must not raise.
        handle_task_run_completed(
            _task_run(state={"autoresearch_training_run_id": "00000000-0000-0000-0000-0000000000ff"})
        )

    def test_marks_failed_on_failed_task_run(self) -> None:
        pipeline = self._make_pipeline()
        training_run = self._make_training_run(pipeline)
        tr = _task_run(status="failed", state={"autoresearch_training_run_id": str(training_run.id)})
        tr.error_message = "sandbox crashed"

        handle_task_run_completed(tr)

        training_run.refresh_from_db()
        assert training_run.status == AutoresearchTrainingRun.Status.FAILED
        assert "sandbox crashed" in training_run.error

    def test_idempotency_guard_skips_already_completed(self) -> None:
        pipeline = self._make_pipeline()
        training_run = self._make_training_run(pipeline, status=AutoresearchTrainingRun.Status.COMPLETED)
        self._record_iteration(training_run)
        handle_task_run_completed(_task_run(state={"autoresearch_training_run_id": str(training_run.id)}))
        # No new champion materialized — the run was already finalized by the agent.
        assert AutoresearchModel.objects.filter(pipeline=pipeline).count() == 0

    def test_finalizes_when_agent_recorded_iterations(self) -> None:
        pipeline = self._make_pipeline()
        training_run = self._make_training_run(pipeline)
        self._record_iteration(training_run, number=0, status="discarded", holdout=0.6)
        self._record_iteration(training_run, number=1, status="kept", holdout=0.82)

        handle_task_run_completed(_task_run(state={"autoresearch_training_run_id": str(training_run.id)}))

        training_run.refresh_from_db()
        assert training_run.status == AutoresearchTrainingRun.Status.COMPLETED
        champion = AutoresearchModel.objects.get(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION)
        assert champion.holdout_score == 0.82
        assert champion.source_training_run == training_run
        # First champion takes the pipeline live so the daily coordinator scores it.
        pipeline.refresh_from_db()
        assert pipeline.status == AutoresearchPipeline.Status.RUNNING

    def test_promotion_does_not_reactivate_non_draft_pipeline(self) -> None:
        pipeline = self._make_pipeline(status=AutoresearchPipeline.Status.PAUSED)
        training_run = self._make_training_run(pipeline)
        self._record_iteration(training_run, number=0, status="kept", holdout=0.82)

        handle_task_run_completed(_task_run(state={"autoresearch_training_run_id": str(training_run.id)}))

        AutoresearchModel.objects.get(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION)
        pipeline.refresh_from_db()
        assert pipeline.status == AutoresearchPipeline.Status.PAUSED

    def test_marks_failed_when_no_iterations(self) -> None:
        pipeline = self._make_pipeline()
        training_run = self._make_training_run(pipeline)

        handle_task_run_completed(_task_run(state={"autoresearch_training_run_id": str(training_run.id)}))

        training_run.refresh_from_db()
        assert training_run.status == AutoresearchTrainingRun.Status.FAILED
        assert "no iterations" in training_run.error.lower()
        assert AutoresearchModel.objects.filter(pipeline=pipeline).count() == 0

    def test_promotion_takes_bootstrapping_pipeline_live(self) -> None:
        pipeline = self._make_pipeline(status=AutoresearchPipeline.Status.BOOTSTRAPPING)
        training_run = self._make_training_run(pipeline)
        self._record_iteration(training_run, number=0, status="kept", holdout=0.82)

        handle_task_run_completed(_task_run(state={"autoresearch_training_run_id": str(training_run.id)}))

        AutoresearchModel.objects.get(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION)
        pipeline.refresh_from_db()
        assert pipeline.status == AutoresearchPipeline.Status.RUNNING

    @parameterized.expand(
        [
            (AutoresearchPipeline.Status.BOOTSTRAPPING, AutoresearchPipeline.Status.DRAFT),
            (AutoresearchPipeline.Status.RUNNING, AutoresearchPipeline.Status.RUNNING),
            (AutoresearchPipeline.Status.PAUSED, AutoresearchPipeline.Status.PAUSED),
        ]
    )
    def test_failed_run_reverts_only_bootstrapping(self, start_status: str, expected_status: str) -> None:
        pipeline = self._make_pipeline(status=start_status)
        training_run = self._make_training_run(pipeline)
        tr = _task_run(status="failed", state={"autoresearch_training_run_id": str(training_run.id)})

        handle_task_run_completed(tr)

        training_run.refresh_from_db()
        pipeline.refresh_from_db()
        assert training_run.status == AutoresearchTrainingRun.Status.FAILED
        assert pipeline.status == expected_status
