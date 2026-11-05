from uuid import uuid4

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from products.data_modeling.backend.forms import ClearNodeSuspensionsForm
from products.data_modeling.backend.logic.node_suspension import unsuspend_nodes
from products.data_modeling.backend.logic.node_suspension_selection import Marker
from products.data_modeling.backend.logic.tier_run_report import build_tier_runs, untargeted_nodes
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.node import Node

SUSPENSION_PREVIEW_SESSION_KEY = "data_modeling_suspension_preview"


@admin.register(DAG)
class DataModelingDAGAdmin(admin.ModelAdmin):
    change_list_template = "admin/data_modeling/dag_change_list.html"
    list_display = ("id", "name", "team_link", "sync_frequency_interval", "tiers_link")
    list_display_links = ("id", "name")
    list_select_related = ("team",)
    search_fields = ("id", "name", "team__id", "team__name")
    raw_id_fields = ("team", "created_by")
    readonly_fields = ("id", "created_at", "updated_at", "tiers_link")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: DAG | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: DAG | None = None) -> bool:
        return False

    def get_urls(self):
        return [
            path(
                "clear-suspensions/",
                self.admin_site.admin_view(self.clear_suspensions_view),
                name="data_modeling_clear_node_suspensions",
            ),
            path(
                "<path:object_id>/tiers/",
                self.admin_site.admin_view(self.tiers_view),
                name="data_modeling_dag_tiers",
            ),
            *super().get_urls(),
        ]

    def changelist_view(self, request: HttpRequest, extra_context: dict | None = None) -> HttpResponse:
        return super().changelist_view(
            request,
            extra_context={
                **(extra_context or {}),
                "can_clear_suspensions": request.user.has_perm("data_modeling.change_node"),
            },
        )

    def _clear_suspension_preview(self, request: HttpRequest) -> HttpResponse:
        preview = request.session.get(SUSPENSION_PREVIEW_SESSION_KEY)
        if not preview or request.POST.get("preview_token") != preview["token"]:
            self.message_user(request, "Preview the suspensions again before clearing them.", messages.ERROR)
            return redirect("admin:data_modeling_clear_node_suspensions")

        del request.session[SUSPENSION_PREVIEW_SESSION_KEY]
        resumed_by = preview.get("by", f"admin:{request.user.pk}")
        cleared = 0
        for item in preview["markers"]:
            node = Node.objects.filter(pk=item["node_id"], team_id=item["team_id"]).first()
            if node is None:
                continue
            marker = Marker(node=node, engine=item["engine"], at=item["at"], reason="")
            # The reset and its audit entry commit together, so a failed log write cannot leave an unaudited reset.
            with transaction.atomic():
                if unsuspend_nodes([node], by=resumed_by, engine=marker.engine, only_if=marker.unchanged):
                    cleared += 1
                    self.log_change(request, node, f"Cleared {marker.engine} suspension. By / note: {resumed_by}")
        skipped = len(preview["markers"]) - cleared
        self.message_user(
            request,
            f"Cleared {cleared} suspension(s). Left {skipped} suspension(s) that changed or no longer exist.",
            messages.SUCCESS,
        )
        return redirect("admin:data_modeling_clear_node_suspensions")

    def clear_suspensions_view(self, request: HttpRequest) -> HttpResponse:
        if not request.user.has_perm("data_modeling.change_node"):
            raise PermissionDenied
        if request.method == "POST" and request.POST.get("action") == "clear":
            return self._clear_suspension_preview(request)

        form = ClearNodeSuspensionsForm(request.POST if request.method == "POST" else None)
        markers: list[Marker] | None = None
        token = ""
        resumed_by = f"admin:{request.user.pk}"
        if request.method == "POST":
            request.session.pop(SUSPENSION_PREVIEW_SESSION_KEY, None)
            if form.is_valid():
                try:
                    markers = form.matching_markers()
                except forms.ValidationError as error:
                    form.add_error(None, error)
                else:
                    token = str(uuid4())
                    resumed_by = form.cleaned_data["by"] or resumed_by
                    request.session[SUSPENSION_PREVIEW_SESSION_KEY] = {
                        "token": token,
                        "by": resumed_by,
                        "markers": [
                            {
                                "node_id": str(marker.node.pk),
                                "team_id": marker.node.team_id,
                                "engine": marker.engine,
                                "at": marker.at,
                            }
                            for marker in markers
                        ],
                    }

        return render(
            request,
            "admin/data_modeling/clear_node_suspensions.html",
            {
                **self.admin_site.each_context(request),
                "title": "Clear node suspensions",
                "opts": self.model._meta,
                "form": form,
                "markers": markers,
                "preview_token": token,
                "resumed_by": resumed_by,
            },
        )

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
