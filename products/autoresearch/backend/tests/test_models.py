from datetime import date
from typing import Any

from posthog.test.base import BaseTest

from django.contrib import admin as django_admin
from django.db import IntegrityError, transaction
from django.test import RequestFactory

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.team import Team

from products.autoresearch.backend import admin as admin_module
from products.autoresearch.backend.models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchRun,
    AutoresearchSuggestion,
    AutoresearchTrainingRun,
)


class TestAutoresearchModels(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.pipeline = AutoresearchPipeline.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, name="p1", target_event="$pageview"
        )

    def _other_team_pipeline(self) -> AutoresearchPipeline:
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other")
        return AutoresearchPipeline.objects.for_team(other_team.pk).create(
            team_id=other_team.pk, name="p2", target_event="$pageview"
        )

    def test_save_overwrites_a_mismatched_team_with_the_pipelines(self) -> None:
        other = self._other_team_pipeline()
        run = AutoresearchTrainingRun(pipeline=other, team_id=self.team.pk)
        run.save()
        assert run.team_id == other.team_id

    def test_partial_save_of_the_pipeline_persists_the_derived_team(self) -> None:
        other = self._other_team_pipeline()
        run = AutoresearchTrainingRun.objects.for_team(self.team.pk).create(pipeline=self.pipeline)
        run.pipeline = other
        run.save(update_fields=["pipeline"])
        run.refresh_from_db()
        assert run.team_id == other.team_id

    def _create(self, model_cls: type[Any], **fields: Any) -> Any:
        if model_cls is AutoresearchPipeline:
            return AutoresearchPipeline.objects.for_team(self.team.pk).create(
                team_id=self.team.pk, name="p4", target_event="$pageview", **fields
            )
        if model_cls is AutoresearchModel:
            fields = {"recipe_hash": "a", "model_recipe": {}, **fields}
        elif model_cls is AutoresearchRun:
            fields = {"run_type": AutoresearchRun.RunType.INFERENCE, **fields}
        elif model_cls is AutoresearchIteration:
            fields = {
                "training_run": AutoresearchTrainingRun.objects.for_team(self.team.pk).create(pipeline=self.pipeline),
                "iteration_number": 1,
                "recipe_hash": "a",
                "recipe_snapshot": {},
                "status": AutoresearchIteration.Status.KEPT,
                **fields,
            }
        return model_cls.objects.for_team(self.team.pk).create(pipeline=self.pipeline, **fields)

    def test_save_rejects_a_relation_from_another_pipeline(self) -> None:
        other = self._other_team_pipeline()
        foreign_run = AutoresearchTrainingRun.objects.for_team(other.team_id).create(pipeline=other)
        with self.assertRaisesRegex(ValueError, "training_run"):
            AutoresearchIteration(
                pipeline=self.pipeline,
                training_run=foreign_run,
                iteration_number=1,
                recipe_snapshot={},
                status=AutoresearchIteration.Status.KEPT,
            ).save()

    def test_only_one_champion_per_pipeline(self) -> None:
        AutoresearchModel.objects.for_team(self.team.pk).create(
            pipeline=self.pipeline, role=AutoresearchModel.Role.CHAMPION, recipe_hash="a", model_recipe={}
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            AutoresearchModel.objects.for_team(self.team.pk).create(
                pipeline=self.pipeline, role=AutoresearchModel.Role.CHAMPION, recipe_hash="b", model_recipe={}
            )

    def test_iteration_budget_remaining_fills_from_the_budget_only_at_creation(self) -> None:
        pipeline = AutoresearchPipeline.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, name="p3", target_event="$pageview", iteration_budget=10
        )
        assert pipeline.iteration_budget_remaining == 10

        pipeline.iteration_budget_remaining = None
        pipeline.save()
        pipeline.refresh_from_db()
        assert pipeline.iteration_budget_remaining is None

    @parameterized.expand(
        [
            (AutoresearchModel, {"holdout_score": 2.0}),
            (AutoresearchModel, {"realized_score": -1.0}),
            (AutoresearchModel, {"trained_on_start": date(2026, 2, 1), "trained_on_end": date(2026, 1, 1)}),
            (AutoresearchTrainingRun, {"best_holdout_score": 1.5}),
            (AutoresearchTrainingRun, {"iteration_budget": 0}),
            (AutoresearchTrainingRun, {"iteration_count": -1}),
            (AutoresearchIteration, {"holdout_score": 2.0}),
            (AutoresearchIteration, {"agent_confidence": -0.5}),
            (AutoresearchRun, {"rows_scored": -1}),
            (AutoresearchPipeline, {"iteration_budget_remaining": -1}),
        ]
    )
    def test_out_of_range_values_are_rejected(self, model_cls: type[Any], fields: dict[str, Any]) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create(model_cls, **fields)

    def test_admin_form_rejects_a_relation_from_another_pipeline(self) -> None:
        other = self._other_team_pipeline()
        foreign_model = AutoresearchModel.objects.for_team(other.team_id).create(
            pipeline=other, recipe_hash="a", model_recipe={}
        )
        request = RequestFactory().get("/admin/")
        request.user = self.user
        model_admin = admin_module.AutoresearchRunAdmin(AutoresearchRun, django_admin.site)
        form = model_admin.get_form(request)(
            data={
                "pipeline": str(self.pipeline.pk),
                "model": str(foreign_model.pk),
                "run_type": AutoresearchRun.RunType.INFERENCE,
                "status": AutoresearchRun.Status.PENDING,
                "metrics": "{}",
            }
        )
        assert not form.is_valid()
        assert "model" in form.errors

    def test_admin_works_without_team_context(self) -> None:
        AutoresearchRun.objects.for_team(self.team.pk).create(
            pipeline=self.pipeline, run_type=AutoresearchRun.RunType.INFERENCE
        )
        request = RequestFactory().get("/admin/")
        request.user = self.user
        admins = (
            (AutoresearchPipeline, admin_module.AutoresearchPipelineAdmin),
            (AutoresearchTrainingRun, admin_module.AutoresearchTrainingRunAdmin),
            (AutoresearchModel, admin_module.AutoresearchModelAdmin),
            (AutoresearchRun, admin_module.AutoresearchRunAdmin),
        )
        for model, admin_class in admins:
            model_admin = admin_class(model, django_admin.site)
            list(model_admin.get_queryset(request))
            model_admin.get_form(request)()

    def test_admin_locks_child_rows_to_their_pipeline(self) -> None:
        request = RequestFactory().get("/admin/")
        request.user = self.user
        run = AutoresearchTrainingRun.objects.for_team(self.team.pk).create(pipeline=self.pipeline)
        admins = (
            (AutoresearchTrainingRun, admin_module.AutoresearchTrainingRunAdmin),
            (AutoresearchModel, admin_module.AutoresearchModelAdmin),
            (AutoresearchSuggestion, admin_module.AutoresearchSuggestionAdmin),
        )
        for model, admin_class in admins:
            model_admin = admin_class(model, django_admin.site)
            assert "pipeline" not in model_admin.get_readonly_fields(request)
            assert "pipeline" in model_admin.get_readonly_fields(request, run)

        model_admin = admin_module.AutoresearchModelAdmin(AutoresearchModel, django_admin.site)
        assert model_admin.has_add_permission(request) is False
