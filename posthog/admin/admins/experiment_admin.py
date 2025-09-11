import copy

from django.contrib import admin, messages
from django.db import transaction
from django.forms import ModelForm
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from posthog.models import (
    Cohort,
    Experiment,
    ExperimentHoldout,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
    FeatureFlag,
)
from posthog.models.utils import convert_legacy_metrics


class ExperimentAdminForm(ModelForm):
    class Meta:
        model = Experiment
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Limit the queryset of the exposure_cohort and holdout fields to the team
        # Otherwise, the queryset will fetch _all_ cohorts and holdouts for _all_ teams,
        # which is a lot and quite slow.
        if self.instance and self.instance.pk:
            if "exposure_cohort" in self.fields:
                self.fields["exposure_cohort"].queryset = Cohort.objects.filter(team=self.instance.team)  # type: ignore
            if "holdout" in self.fields:
                self.fields["holdout"].queryset = ExperimentHoldout.objects.filter(team=self.instance.team)  # type: ignore
            if "feature_flag" in self.fields:
                self.fields["feature_flag"].queryset = FeatureFlag.objects.filter(team=self.instance.team)  # type: ignore


def has_legacy_metric(metrics):
    if not metrics:
        return False
    for metric in metrics:
        kind = metric.get("kind")
        if kind in ("ExperimentFunnelsQuery", "ExperimentTrendsQuery"):
            return True
    return False


class ExperimentAdmin(admin.ModelAdmin):
    form = ExperimentAdminForm
    list_display = (
        "id",
        "name",
        "engine",
        "migrated_links",
        "team_link",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    autocomplete_fields = ("team", "created_by")
    ordering = ("-created_at",)

    @admin.display(description="Team")
    def team_link(self, experiment: Experiment):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[experiment.team.pk]),
            experiment.team.name,
        )

    @admin.display(description="Engine")
    def engine(self, experiment: Experiment):
        all_metrics = (experiment.metrics or []) + (experiment.metrics_secondary or [])
        if has_legacy_metric(all_metrics):
            return format_html('<span style="color: orange;">Legacy</span>')
        return ""

    @admin.display(description="")
    def migrated_links(self, experiment: Experiment):
        if experiment.stats_config and "migrated_from" in experiment.stats_config:
            return format_html(
                '<a href="{}">Migrated From: {}</a>',
                reverse("admin:posthog_experiment_change", args=[experiment.stats_config["migrated_from"]]),
                experiment.stats_config["migrated_from"],
            )
        if experiment.stats_config and "migrated_to" in experiment.stats_config:
            return format_html(
                '<a href="{}">Migrated To: {}</a>',
                reverse("admin:posthog_experiment_change", args=[experiment.stats_config["migrated_to"]]),
                experiment.stats_config["migrated_to"],
            )
        return ""

    change_form_template = "admin/posthog/experiment/change_form.html"

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}

        obj = self.get_object(request, object_id)
        if obj is None:
            messages.error(request, "Experiment not found")
            return redirect("admin:posthog_experiment_changelist")

        all_metrics = (obj.metrics or []) + (obj.metrics_secondary or [])
        extra_context["show_migration"] = has_legacy_metric(all_metrics)

        # Get all related ExperimentSavedMetric objects
        shared_metrics = obj.saved_metrics.all()
        shared_metrics_status = []
        for metric in shared_metrics:
            kind = metric.query.get("kind") if metric.query else None
            is_legacy = kind in ("ExperimentFunnelsQuery", "ExperimentTrendsQuery")
            migrated = bool(metric.metadata and "migrated_to" in metric.metadata)
            shared_metrics_status.append(
                {
                    "id": metric.id,
                    "name": metric.name,
                    "is_legacy": is_legacy,
                    "migrated": migrated,
                    "migrate_url": reverse("admin:posthog_experimentsavedmetric_change", args=[metric.id]),
                }
            )
        extra_context["shared_metrics_status"] = shared_metrics_status

        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/migrate/",
                self.admin_site.admin_view(self.migrate_experiment),
                name="experiment_migrate",
            ),
        ]
        return custom_urls + urls

    def migrate_experiment(self, request, object_id):
        try:
            with transaction.atomic():
                original = Experiment.objects.select_for_update().get(pk=object_id)

                if original.stats_config and original.stats_config.get("migrated_to"):
                    messages.warning(request, f"Experiment already migrated to {original.stats_config['migrated_to']}")
                    return redirect("admin:posthog_experiment_change", original.stats_config["migrated_to"])

                new_experiment = Experiment()

                # copy all fields... almost all...
                excluded_fields = ["id", "created_at", "key"]
                for field in original._meta.fields:
                    if field.name not in excluded_fields:
                        value = getattr(original, field.name)
                        # Deep copy dicts to avoid shared references
                        if isinstance(value, dict):
                            value = copy.deepcopy(value)
                        setattr(new_experiment, field.name, value)

                # migrate metrics and secondary metrics
                new_experiment.metrics = convert_legacy_metrics(original.metrics)
                new_experiment.metrics_secondary = convert_legacy_metrics(original.metrics_secondary)

                # update the migrated from relation
                if new_experiment.stats_config is None:
                    new_experiment.stats_config = {}
                new_experiment.stats_config["migrated_from"] = int(object_id)

                # save the experiment, we need this for referential integrity
                new_experiment.save()

                # find the shared metrics "migrated to" and create new relationships
                # check if all saved metrics have been migrated
                for metric in original.saved_metrics.all():
                    kind = metric.query.get("kind") if metric.query else None
                    is_legacy = kind in ("ExperimentFunnelsQuery", "ExperimentTrendsQuery")
                    migrated = bool(metric.metadata and "migrated_to" in metric.metadata)

                    # bail with an exception if the metric is legacy and has not been migrated
                    if is_legacy and not migrated:
                        raise Exception(f"Saved metric {metric.id} has not been migrated yet")

                    # because we need metadata from the through table, we can't just do
                    # experiment.saved_metrics.add. We need to create the relationship by hand
                    original_to_saved_metric = ExperimentToSavedMetric.objects.get(
                        experiment=original, saved_metric=metric
                    )

                    # if is legacy, get the migrated metric, otherwise, keep the id from the original experiment
                    metric_id = metric.metadata["migrated_to"] if is_legacy else metric.id

                    saved_metric = ExperimentSavedMetric.objects.get(id=metric_id)

                    # Create the new through object with the same metadata
                    ExperimentToSavedMetric.objects.create(
                        experiment=new_experiment,
                        saved_metric=saved_metric,
                        metadata=copy.deepcopy(original_to_saved_metric.metadata),
                    )

                # update the migrated to soft relation
                if original.stats_config is None:
                    original.stats_config = {}
                original.stats_config["migrated_to"] = new_experiment.id
                original.save(update_fields=["stats_config"])

            messages.success(request, "Experiment migrated successfully")
            return redirect("admin:posthog_experiment_change", new_experiment.pk)
        except Experiment.DoesNotExist:
            messages.error(request, "Experiment not found")
            return redirect("admin:posthog_experiment_changelist")
        except Exception as e:
            messages.error(request, f"Error migrating experiment: {e}")
            return redirect("admin:posthog_experiment_change", object_id)
