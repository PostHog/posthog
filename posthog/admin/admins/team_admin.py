from django.contrib import admin
from django.utils.html import format_html
from posthog.admin.inlines.action_inline import ActionInline
from posthog.admin.inlines.group_type_mapping_inline import GroupTypeMappingInline

from posthog.models import Team


class TeamAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "organization_link",
        "organization_id",
        "created_at",
        "updated_at",
    )
    list_display_links = ("id", "name")
    list_select_related = ("organization",)
    search_fields = (
        "id",
        "name",
        "organization__id",
        "organization__name",
        "api_token",
    )
    readonly_fields = ["organization", "primary_dashboard", "test_account_filters"]
    inlines = [GroupTypeMappingInline, ActionInline]
    fieldsets = [
        (
            None,
            {
                "fields": [
                    "name",
                    "organization",
                ],
            },
        ),
        (
            "General",
            {
                "classes": ["collapse"],
                "fields": [
                    "api_token",
                    "timezone",
                    "slack_incoming_webhook",
                    "primary_dashboard",
                ],
            },
        ),
        (
            "Onboarding",
            {
                "classes": ["collapse"],
                "fields": [
                    "is_demo",
                    "completed_snippet_onboarding",
                    "ingested_event",
                    "signup_token",
                ],
            },
        ),
        (
            "Settings",
            {
                "classes": ["collapse"],
                "fields": [
                    "anonymize_ips",
                    "autocapture_opt_out",
                    "autocapture_exceptions_opt_in",
                    "session_recording_opt_in",
                    "capture_console_log_opt_in",
                    "capture_performance_opt_in",
                    "session_recording_sample_rate",
                    "session_recording_minimum_duration_milliseconds",
                    "session_recording_linked_flag",
                    "data_attributes",
                    "session_recording_version",
                    "access_control",
                    "inject_web_apps",
                    "extra_settings",
                ],
            },
        ),
        (
            "Filters",
            {
                "classes": ["collapse"],
                "fields": [
                    "test_account_filters",
                    "test_account_filters_default_checked",
                    "path_cleaning_filters",
                ],
            },
        ),
    ]

    def organization_link(self, team: Team):
        return format_html(
            '<a href="/admin/posthog/organization/{}/change/">{}</a>',
            team.organization.pk,
            team.organization.name,
        )
