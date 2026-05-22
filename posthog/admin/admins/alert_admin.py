from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from posthog.admin.paginators.no_count_paginator import NoCountPaginator

from products.alerts.backend.models.alert import AlertConfiguration


@admin.register(AlertConfiguration)
class AlertConfigurationAdmin(admin.ModelAdmin):
    show_full_result_count = False
    paginator = NoCountPaginator

    list_display = (
        "id",
        "name",
        "team_link",
        "state",
        "enabled",
        "calculation_interval",
        "next_check_at",
        "last_notified_at",
        "created_at",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization")
    list_filter = ("state", "enabled", "calculation_interval", "investigation_agent_enabled")
    search_fields = ("id", "name", "team__id", "team__name", "team__organization__name")
    ordering = ("-id",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Team")
    def team_link(self, alert: AlertConfiguration):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[alert.team_id]),
            alert.team.name,
        )
