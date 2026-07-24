from typing import Any

from django.contrib import admin, messages
from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

from posthog.admin.filters import DeletedFilter

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile


class DashboardTileInline(admin.TabularInline):
    extra = 0
    model = DashboardTile
    autocomplete_fields = ("insight", "text", "team")
    readonly_fields = ("filters_hash",)


@admin.register(Dashboard)
class DashboardAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "team_link",
        "organization_link",
        "created_at",
        "created_by",
        "deleted",
    )
    list_display_links = ("id", "name")
    list_filter = (DeletedFilter,)
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    readonly_fields = (
        "last_accessed_at",
        "deprecated_tags",
        "deprecated_tags_v2",
        "share_token",
    )
    autocomplete_fields = ("team", "created_by")
    ordering = ("-created_at", "creation_mode")
    inlines = (DashboardTileInline,)
    actions = ["restore_selected"]

    def get_queryset(self, request):
        return Dashboard.objects_including_soft_deleted.all()

    def get_actions(self, request: HttpRequest) -> dict[str, Any]:
        # Drop the built-in hard-delete: dashboards are soft-deleted product-side.
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    @admin.action(
        permissions=["change"],
        description="Restore selected dashboards (incl. tiles and co-deleted insights)",
    )
    def restore_selected(self, request: HttpRequest, queryset: QuerySet[Dashboard]) -> None:
        from products.dashboards.backend.api.dashboard import (  # noqa: PLC0415 — keeps the heavy API module off the django.setup() path
            DashboardSerializer,
        )

        dashboards = list(queryset.filter(deleted=True))
        # Count before restoring: the changelist queryset carries the deleted=True filter, so a
        # later count() would exclude the rows we just un-deleted and skew "skipped" negative.
        skipped = queryset.count() - len(dashboards)
        # Same path as PATCH {"deleted": false}: restores tiles, co-deleted insights, FileSystem
        # entries, and logs the restore via ModelActivityMixin. Atomic so a mid-batch failure
        # can't leave a dashboard back without its tiles.
        with transaction.atomic():
            for dashboard in dashboards:
                DashboardSerializer._undo_delete_related_tiles(dashboard)
                dashboard.deleted = False
                dashboard.save()

        message = f"Restored {len(dashboards)} dashboards."
        if skipped:
            message += f" Skipped {skipped} that were not soft-deleted."
        self.message_user(request, message, messages.SUCCESS)

    @admin.display(description="Team")
    def team_link(self, dashboard: Dashboard):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[dashboard.team.pk]),
            dashboard.team.name,
        )

    @admin.display(description="Organization")
    def organization_link(self, dashboard: Dashboard):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_organization_change", args=[dashboard.team.organization.pk]),
            dashboard.team.organization.name,
        )
