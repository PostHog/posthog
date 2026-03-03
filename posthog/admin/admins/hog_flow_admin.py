from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from posthog.models.hog_flow.hog_flow import HogFlow


class HogFlowAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "status", "version", "team_link", "created_at")
    list_filter = (
        ("status", admin.ChoicesFieldListFilter),
        ("updated_at", admin.DateFieldListFilter),
    )
    list_select_related = ("team",)
    search_fields = ("name", "team__name", "team__organization__name")
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "version",
        "team",
        "team_link",
        "created_by",
        "created_at",
        "updated_at",
        "trigger",
        "trigger_masking",
        "conversion",
        "edges",
        "actions",
        "variables",
        "billable_action_types",
    )
    fields = (
        "name",
        "description",
        "status",
        "exit_condition",
        "abort_action",
        "version",
        "team_link",
        "created_by",
        "created_at",
        "updated_at",
        "trigger",
        "trigger_masking",
        "conversion",
        "edges",
        "actions",
        "variables",
        "billable_action_types",
    )

    @admin.display(description="Team")
    def team_link(self, hog_flow: HogFlow):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[hog_flow.team.pk]),
            hog_flow.team.name,
        )
