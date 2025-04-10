from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse

from posthog.models import Survey


class SurveyAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "team_link",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    autocomplete_fields = ("team", "created_by")
    ordering = ("-created_at",)

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        for field in [
            "start_date",
            "end_date",
            "responses_limit",
            "iteration_count",
            "iteration_frequency_days",
            "iteration_start_dates",
            "current_iteration",
            "current_iteration_start_date",
            "actions",
        ]:
            form.base_fields[field].required = False
        return form

    @admin.display(description="Team")
    def team_link(self, survey: Survey):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[survey.team.pk]),
            survey.team.name,
        )
