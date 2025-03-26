from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse

from posthog.models import DataColorTheme


class DataColorThemeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "team_link",
    )
    readonly_fields = ("team",)

    @admin.display(description="Team")
    def team_link(self, data_color_theme: DataColorTheme):
        if not data_color_theme.team:
            return "-"
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[data_color_theme.team.pk]),
            data_color_theme.team.name,
        )
