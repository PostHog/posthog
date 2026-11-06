"""Test-support facade for autoresearch.

Suites outside this product plant rows through here instead of importing the models. The model is team-scoped and fail-closed, so this opens the scope the insert needs.
"""

from uuid import UUID

from posthog.models.scoping import team_scope

from products.autoresearch.backend.models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchTrainingRun,
)


def create_pipeline(*, team_id: int, name: str, target_event: str = "$pageview") -> UUID:
    with team_scope(team_id):
        pipeline = AutoresearchPipeline.objects.create(team_id=team_id, name=name, target_event=target_event)
    return pipeline.pk


def create_training_run(*, pipeline_id: UUID) -> UUID:
    pipeline = AutoresearchPipeline.all_teams.get(pk=pipeline_id)
    with team_scope(pipeline.team_id):
        training_run = AutoresearchTrainingRun.objects.create(pipeline=pipeline)
    return training_run.pk


def create_iteration(*, training_run_id: UUID, iteration_number: int = 1) -> UUID:
    training_run = AutoresearchTrainingRun.all_teams.select_related("pipeline").get(pk=training_run_id)
    with team_scope(training_run.team_id):
        iteration = AutoresearchIteration.objects.create(
            pipeline=training_run.pipeline,
            training_run=training_run,
            iteration_number=iteration_number,
            recipe_hash="0" * 64,
            recipe_snapshot={},
            status=AutoresearchIteration.Status.KEPT,
        )
    return iteration.pk


def create_model(*, pipeline_id: UUID) -> UUID:
    pipeline = AutoresearchPipeline.all_teams.get(pk=pipeline_id)
    with team_scope(pipeline.team_id):
        model = AutoresearchModel.objects.create(pipeline=pipeline, recipe_hash="0" * 64, model_recipe={})
    return model.pk
