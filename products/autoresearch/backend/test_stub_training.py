from posthog.test.base import BaseTest

from products.autoresearch.backend.models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchTrainingRun,
)
from products.autoresearch.backend.stub_training import run_stub_training


class TestStubTraining(BaseTest):
    def _make_pipeline(self, **kwargs) -> AutoresearchPipeline:
        defaults = {
            "team": self.team,
            "created_by": self.user,
            "name": "Test Pipeline",
            "target_event": "$pageview",
            "horizon_days": 7,
            "iteration_budget": 50,
            "iteration_budget_remaining": 50,
        }
        defaults.update(kwargs)
        return AutoresearchPipeline.objects.create(**defaults)

    def test_creates_training_run_and_champion(self):
        pipeline = self._make_pipeline()
        training_run = run_stub_training(pipeline=pipeline, iteration_budget=10)

        assert training_run.status == AutoresearchTrainingRun.Status.COMPLETED
        assert training_run.iteration_count == 1
        assert training_run.best_holdout_score == 0.7

        champion = AutoresearchModel.objects.get(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION)
        assert champion.holdout_score == 0.7
        assert champion.is_preliminary is True
        assert champion.source_training_run == training_run
        assert champion.model_recipe is not None
        assert "feature_sql" in champion.model_recipe

    def test_creates_one_iteration(self):
        pipeline = self._make_pipeline()
        training_run = run_stub_training(pipeline=pipeline, iteration_budget=10)
        iterations = AutoresearchIteration.objects.filter(training_run=training_run)
        assert iterations.count() == 1

    def test_previous_champion_archived(self):
        pipeline = self._make_pipeline()
        run_stub_training(pipeline=pipeline, iteration_budget=10)
        old_champion = AutoresearchModel.objects.get(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION)

        run_stub_training(pipeline=pipeline, iteration_budget=10)

        old_champion.refresh_from_db()
        assert old_champion.role == AutoresearchModel.Role.ARCHIVED

        new_champion = AutoresearchModel.objects.get(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION)
        assert new_champion.pk != old_champion.pk

    def test_pipeline_status_set_to_running(self):
        pipeline = self._make_pipeline(status=AutoresearchPipeline.Status.DRAFT)
        run_stub_training(pipeline=pipeline, iteration_budget=10)
        pipeline.refresh_from_db()
        assert pipeline.status == AutoresearchPipeline.Status.RUNNING
