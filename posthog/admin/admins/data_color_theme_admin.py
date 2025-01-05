from django.contrib import admin
from django.utils.html import format_html

from posthog.models import DataColorTheme


class DataColorThemeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "team_link",
    )
    readonly_fields = ("team",)

    @admin.display(description="Team")
    def team_link(self, theme: DataColorTheme):
        if theme.team is None:
            return None
        return format_html(
            '<a href="/admin/posthog/team/{}/change/">{}</a>',
            theme.team.pk,
            theme.team.name,
        )
