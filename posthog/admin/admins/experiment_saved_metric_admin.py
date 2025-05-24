from django.contrib import admin
from django.db import transaction
from django.utils.html import format_html
from django.urls import reverse, path
from django.shortcuts import redirect
from django.contrib import messages
from posthog.models import ExperimentSavedMetric
from posthog.models.utils import convert_legacy_metric


class ExperimentSavedMetricAdmin(admin.ModelAdmin):
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
    def team_link(self, saved_metric: ExperimentSavedMetric):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[saved_metric.team.pk]),
            saved_metric.team.name,
        )

    @admin.display(description="Engine")
    def engine(self, saved_metric: ExperimentSavedMetric):
        kind = saved_metric.query.get("kind") if saved_metric.query else None
        if kind == "ExperimentFunnelsQuery" or kind == "ExperimentTrendsQuery":
            return format_html('<span style="color: orange;">Legacy</span>')
        return ""

    @admin.display(description="")
    def migrated_links(self, saved_metric: ExperimentSavedMetric):
        if saved_metric.metadata and "migrated_from" in saved_metric.metadata:
            return format_html(
                '<a href="{}">Migrated From {}</a>',
                reverse("admin:posthog_experimentsavedmetric_change", args=[saved_metric.metadata["migrated_from"]]),
                saved_metric.metadata["migrated_from"],
            )
        if saved_metric.metadata and "migrated_to" in saved_metric.metadata:
            return format_html(
                '<a href="{}">Migrated To {}</a>',
                reverse("admin:posthog_experimentsavedmetric_change", args=[saved_metric.metadata["migrated_to"]]),
                saved_metric.metadata["migrated_to"],
            )
        return ""

    change_form_template = "admin/posthog/experimentsavedmetric/change_form.html"

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        kind = obj.query.get("kind") if obj.query else None
        extra_context["show_migration"] = kind == "ExperimentFunnelsQuery" or kind == "ExperimentTrendsQuery"
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/migrate/",
                self.admin_site.admin_view(self.migrate_metric),
                name="experimentsavedmetric_migrate",
            ),
        ]
        return custom_urls + urls

    def migrate_metric(self, request, object_id):
        original = self.get_object(request, object_id)
        if not original:
            messages.error(request, "Metric not found")
            return redirect("admin:posthog_experimentsavedmetric_changelist")

        try:
            with transaction.atomic():
                new_metric = ExperimentSavedMetric()
                new_metric.name = original.name
                new_metric.team = original.team
                new_metric.created_by = original.created_by
                new_metric.query = convert_legacy_metric(original.query)
                new_metric.metadata = {"migrated_from": original.id}
                new_metric.save()

                if original.metadata is None:
                    original.metadata = {}
                original.metadata["migrated_to"] = new_metric.id
                original.save(update_fields=["metadata"])

            messages.success(request, "Metric migrated successfully")
            return redirect("admin:posthog_experimentsavedmetric_change", new_metric.pk)
        except Exception as e:
            messages.error(request, f"Error migrating metric: {e}")
            return redirect("admin:posthog_experimentsavedmetric_change", object_id)
