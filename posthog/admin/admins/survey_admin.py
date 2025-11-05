from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

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
    readonly_fields = ("linked_flag", "targeting_flag", "internal_targeting_flag", "internal_response_sampling_flag")
    ordering = ("-created_at",)

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        # only on individual change page
        if obj:
            readonly_fields.append("actions")
        return readonly_fields

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
            if field in form.base_fields:
                form.base_fields[field].required = False
        return form

    @admin.display(description="Team")
    def team_link(self, survey: Survey):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[survey.team.pk]),
            survey.team.name,
        )
