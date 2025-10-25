from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from posthog.models.group_type_mapping import GroupTypeMapping


class GroupTypeMappingAdmin(admin.ModelAdmin):
    list_display = (
        "group_type_index",
        "group_type",
        "name_singular",
        "name_plural",
        "team_link",
    )
    list_select_related = ("team", "team__organization")
    search_fields = ("name_singular", "team__name", "team__organization__name")
    readonly_fields = ("team", "project", "group_type", "group_type_index", "detail_dashboard")

    @admin.display(description="Team")
    def team_link(self, group_type_mapping: GroupTypeMapping):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[group_type_mapping.team.pk]),
            group_type_mapping.team.name,
        )
