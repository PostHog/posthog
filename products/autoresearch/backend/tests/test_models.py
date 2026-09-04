from posthog.test.base import BaseTest

from django.contrib import admin as django_admin
from django.db import IntegrityError, transaction
from django.test import RequestFactory

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
