from django.contrib import admin
from django.utils.html import format_html

from posthog.models.hog_functions.hog_function import HogFunction, HogFunctionStatus


class HogFunctionAdmin(admin.ModelAdmin):
    list_select_related = ("team",)
    list_display = ("id", "name", "enabled")
    list_filter = (
        ("enabled", admin.BooleanFieldListFilter),
        ("deleted", admin.BooleanFieldListFilter),
        ("updated_at", admin.DateFieldListFilter),
    )
    list_select_related = ("team",)
    search_fields = ("team__name", "team__organization__name")
    ordering = ("-created_at",)
    readonly_fields = (
        "inputs",
        "inputs_schema",
        "filters",
        "bytecode",
        "hog",
        "team",
        "status",
        "created_by",
        "team_link",
        "function_state",
    )
    fields = (
        "name",
        "description",
        "enabled",
        "created_by",
        "icon_url",
        "hog",
        "bytecode",
        "inputs_schema",
        "inputs",
        "filters",
        "template_id",
        "status",
    )

    def status(self, instance: HogFunction):
        return instance.get_status()

    def function_state(self, instance: HogFunction):
        status = instance.get_status()

        return HogFunctionStatus(status).name or "Unknown"

    def team_link(self, instance: HogFunction):
        return format_html(
            '<a href="/admin/posthog/team/{}/change/">{}</a>',
            instance.team.pk,
            instance.team.name,
        )
