from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from posthog.models.scoping import team_scope

from products.autoresearch.backend.models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchRun,
    AutoresearchSuggestion,
    AutoresearchTrainingRun,
)


class ScopedTest(BaseTest):
    # Every model here is fail-closed, so reads and writes need an ambient team.
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(team_scope(self.team.pk))


class TestPipelineTenantDerivation(ScopedTest):
    def setUp(self) -> None:
        super().setUp()
        self.pipeline = AutoresearchPipeline.objects.create(
            team=self.team, name="Test", target_event="$pageview", horizon_days=7
        )

    def test_child_takes_its_team_from_the_pipeline(self) -> None:
        run = AutoresearchTrainingRun.objects.create(pipeline=self.pipeline)
        assert run.team_id == self.team.pk

    def test_a_team_passed_by_the_caller_does_not_win_over_the_pipeline(self) -> None:
        other = self.organization.teams.create(name="Other team")
        run = AutoresearchTrainingRun.objects.create(pipeline=self.pipeline, team=other)
        run.refresh_from_db()
        assert run.team_id == self.team.pk

    def test_iteration_follows_its_training_run_not_the_pipeline_it_was_handed(self) -> None:
        other_pipeline = AutoresearchPipeline.objects.create(
            team=self.team, name="Other", target_event="$pageview", horizon_days=7
        )
        training_run = AutoresearchTrainingRun.objects.create(pipeline=self.pipeline)
        iteration = AutoresearchIteration.objects.create(
            pipeline=other_pipeline,
            training_run=training_run,
            iteration_number=1,
            recipe_hash="abc",
            recipe_snapshot={},
            status=AutoresearchIteration.Status.KEPT,
        )
        iteration.refresh_from_db()
        assert iteration.pipeline_id == self.pipeline.pk


class TestPipelineBudget(ScopedTest):
    def test_remaining_budget_starts_at_the_configured_budget(self) -> None:
        pipeline = AutoresearchPipeline.objects.create(
            team=self.team, name="Test", target_event="$pageview", horizon_days=7, iteration_budget=7
        )
        assert pipeline.iteration_budget_remaining == 7

    def test_spending_the_budget_survives_a_later_save(self) -> None:
        pipeline = AutoresearchPipeline.objects.create(
            team=self.team, name="Test", target_event="$pageview", horizon_days=7, iteration_budget=7
        )
        pipeline.iteration_budget_remaining = 3
        pipeline.save(update_fields=["iteration_budget_remaining"])
        pipeline.refresh_from_db()
        assert pipeline.iteration_budget_remaining == 3


class TestChampionInvariants(ScopedTest):
    def setUp(self) -> None:
        super().setUp()
        self.pipeline = AutoresearchPipeline.objects.create(
            team=self.team, name="Test", target_event="$pageview", horizon_days=7
        )

    def _make_model(self, role: str) -> AutoresearchModel:
        return AutoresearchModel.objects.create(pipeline=self.pipeline, role=role, recipe_hash="abc", model_recipe={})

    def test_a_pipeline_cannot_hold_two_champions(self) -> None:
        self._make_model(AutoresearchModel.Role.CHAMPION)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            self._make_model(AutoresearchModel.Role.CHAMPION)

    def test_challengers_are_not_limited(self) -> None:
        self._make_model(AutoresearchModel.Role.CHALLENGER)
        self._make_model(AutoresearchModel.Role.CHALLENGER)
        assert AutoresearchModel.objects.for_team(self.team.pk).count() == 2


class TestForeignPipelineRelationsAreRejected(ScopedTest):
    def setUp(self) -> None:
        super().setUp()
        self.pipeline = AutoresearchPipeline.objects.create(
            team=self.team, name="Test", target_event="$pageview", horizon_days=7
        )
        self.other = AutoresearchPipeline.objects.create(
            team=self.team, name="Other", target_event="$pageview", horizon_days=7
        )

    def test_run_rejects_a_model_from_another_pipeline(self) -> None:
        foreign = AutoresearchModel.objects.create(
            pipeline=self.other, role=AutoresearchModel.Role.CHAMPION, recipe_hash="abc", model_recipe={}
        )
        with self.assertRaises(ValidationError):
            AutoresearchRun.objects.create(
                pipeline=self.pipeline, model=foreign, run_type=AutoresearchRun.RunType.INFERENCE
            )

    def test_model_rejects_a_source_training_run_from_another_pipeline(self) -> None:
        foreign = AutoresearchTrainingRun.objects.create(pipeline=self.other)
        with self.assertRaises(ValidationError):
            AutoresearchModel.objects.create(
                pipeline=self.pipeline, recipe_hash="abc", model_recipe={}, source_training_run=foreign
            )

    def test_iteration_rejects_a_parent_suggestion_from_another_pipeline(self) -> None:
        foreign = AutoresearchSuggestion.objects.create(pipeline=self.other, prompt="try this")
        training_run = AutoresearchTrainingRun.objects.create(pipeline=self.pipeline)
        with self.assertRaises(ValidationError):
            AutoresearchIteration.objects.create(
                training_run=training_run,
                pipeline=self.pipeline,
                iteration_number=1,
                recipe_hash="abc",
                recipe_snapshot={},
                status=AutoresearchIteration.Status.KEPT,
                parent_suggestion=foreign,
            )
