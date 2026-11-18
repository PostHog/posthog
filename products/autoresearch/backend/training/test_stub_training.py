from posthog.test.base import BaseTest

from parameterized import parameterized

from products.autoresearch.backend.models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchTrainingRun,
)
from products.autoresearch.backend.testing import TeamScopedTestMixin
from products.autoresearch.backend.training.stub import run_stub_training


class TestStubTraining(TeamScopedTestMixin, BaseTest):
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
        assert champion.promoted_at is not None
        iteration = AutoresearchIteration.objects.get(training_run=training_run)
        assert iteration.recipe_snapshot["feature_sql"] == champion.model_recipe["feature_sql"]
        assert champion.model_recipe is not None
        assert "feature_sql" in champion.model_recipe
        # The stub must not count autoresearch's own prediction events — they feed the
        # model its own output once scoring starts.
        assert "NOT startsWith(event, 'autoresearch_')" in champion.model_recipe["feature_sql"]

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

    @parameterized.expand([("stronger", 0.9), ("weaker_than_the_placeholder", 0.6)])
    def test_a_trained_champion_survives_a_stub_run(self, _name, trained_score):
        pipeline = self._make_pipeline()
        trained = AutoresearchModel.objects.create(
            pipeline=pipeline,
            role=AutoresearchModel.Role.CHAMPION,
            recipe_hash="trained",
            model_recipe={},
            holdout_score=trained_score,
        )

        training_run = run_stub_training(pipeline=pipeline, iteration_budget=10)

        trained.refresh_from_db()
        assert trained.role == AutoresearchModel.Role.CHAMPION
        stub_model = AutoresearchModel.objects.get(source_training_run=training_run)
        assert stub_model.role == AutoresearchModel.Role.CHALLENGER

    @parameterized.expand(
        [
            ("draft", AutoresearchPipeline.Status.DRAFT, AutoresearchPipeline.Status.RUNNING),
            ("bootstrapping", AutoresearchPipeline.Status.BOOTSTRAPPING, AutoresearchPipeline.Status.RUNNING),
            ("paused", AutoresearchPipeline.Status.PAUSED, AutoresearchPipeline.Status.PAUSED),
            ("archived", AutoresearchPipeline.Status.ARCHIVED, AutoresearchPipeline.Status.ARCHIVED),
        ]
    )
    def test_pipeline_status_after_stub_run(self, _name, before, after):
        pipeline = self._make_pipeline(status=before)
        run_stub_training(pipeline=pipeline, iteration_budget=10)
        pipeline.refresh_from_db()
        assert pipeline.status == after
