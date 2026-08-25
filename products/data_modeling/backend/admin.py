from django.conf import settings
from django.contrib import admin
from django.http import Http404
from django.shortcuts import render
from django.urls import path, reverse
from django.utils.html import format_html

from products.data_modeling.backend.logic.tier_run_report import build_tier_runs, untargeted_nodes
from products.data_modeling.backend.models.dag import DAG


@admin.register(DAG)
class DataModelingDAGAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "team_link", "sync_frequency_interval", "tiers_link")
    list_display_links = ("id", "name")
    list_select_related = ("team",)
    search_fields = ("id", "name", "team__id", "team__name")
    raw_id_fields = ("team", "created_by")
    readonly_fields = ("id", "created_at", "updated_at", "tiers_link")

    def get_urls(self):
        return [
            path(
                "<path:object_id>/tiers/",
                self.admin_site.admin_view(self.tiers_view),
                name="data_modeling_dag_tiers",
            ),
            *super().get_urls(),
        ]

    @admin.display(description="Team")
    def team_link(self, dag: DAG):
        return format_html(
            '<a href="{}">{} ({})</a>',
            reverse("admin:posthog_team_change", args=[dag.team_id]),
            dag.team.name,
            dag.team_id,
        )

    @admin.display(description="Tiers")
    def tiers_link(self, dag: DAG):
        if not dag.pk:
            return "—"
        return format_html(
            '<a href="{}">schedule tiers &amp; last run</a>', reverse("admin:data_modeling_dag_tiers", args=[dag.pk])
        )

    def tiers_view(self, request, object_id: str):
        dag = self.get_object(request, object_id)
        if dag is None:
            raise Http404("No DAG with that id")

        tiers = build_tier_runs(dag)
        return render(
            request,
            "admin/data_modeling/dag_tiers.html",
            {
                **self.admin_site.each_context(request),
                "title": f"Schedule tiers — {dag.name}",
                "dag": dag,
                "tiers": tiers,
                "untargeted": untargeted_nodes(dag),
                "temporal_ui_host": settings.TEMPORAL_UI_HOST,
                "temporal_namespace": settings.TEMPORAL_NAMESPACE,
            },
        )
