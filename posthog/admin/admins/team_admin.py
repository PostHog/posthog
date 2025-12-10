import tempfile

from django.contrib import admin, messages
from django.core.cache import cache
from django.core.files.uploadedfile import UploadedFile
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import path, reverse
from django.utils.html import escapejs, format_html, mark_safe

from structlog import get_logger

from posthog.admin.inlines.team_marketing_analytics_config_inline import TeamMarketingAnalyticsConfigInline
from posthog.admin.inlines.user_product_list_inline import UserProductListInline
from posthog.models import Team
from posthog.models.remote_config import cache_key_for_team_token
from posthog.models.team.team import DEPRECATED_ATTRS

logger = get_logger()


class TeamAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "organization_link",
        "organization_id",
        "project_link",
        "project_id",
        "created_at",
        "updated_at",
    )
    list_display_links = ("id", "name")
    list_select_related = ("organization", "project")
    search_fields = (
        "id",
        "uuid",
        "name",
        "organization__id",
        "organization__name",
        "project__id",
        "project__name",
        "api_token",
    )
    readonly_fields = [
        "id",
        "uuid",
        "organization",
        "project",
        "primary_dashboard",
        "test_account_filters",
        "created_at",
        "updated_at",
        "internal_properties",
        "remote_config_cache_actions",
        "export_individual_replay",
        "import_individual_replay",
    ]

    exclude = DEPRECATED_ATTRS
    inlines = [TeamMarketingAnalyticsConfigInline, UserProductListInline]

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        self._current_request = request
        return super().changeform_view(request, object_id, form_url, extra_context)

    fieldsets = [
        (
            None,
            {
                "fields": [
                    "name",
                    "id",
                    "uuid",
                    "organization",
                    "project",
                    "internal_properties",
                    "remote_config_cache_actions",
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
                    "week_start_day",
                    "base_currency",
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
                    "autocapture_web_vitals_opt_in",
                    "session_recording_opt_in",
                    "person_processing_opt_out",
                    "capture_console_log_opt_in",
                    "capture_performance_opt_in",
                    "recording_domains",
                    "session_recording_sample_rate",
                    "session_recording_minimum_duration_milliseconds",
                    "session_recording_linked_flag",
                    "session_recording_retention_period",
                    "api_query_rate_limit",
                    "data_attributes",
                    "session_recording_version",
                    "inject_web_apps",
                    "web_analytics_pre_aggregated_tables_enabled",
                    "web_analytics_pre_aggregated_tables_version",
                    "extra_settings",
                    "modifiers",
                    "drop_events_older_than",
                ],
            },
        ),
        (
            "Surveys",
            {
                "classes": ["collapse"],
                "fields": [
                    "surveys_opt_in",
                    "survey_config",
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
        (
            "Session replay actions",
            {
                "classes": ["collapse"],
                "fields": [
                    "export_individual_replay",
                    "import_individual_replay",
                ],
            },
        ),
    ]

    def organization_link(self, team: Team):
        if team.organization:
            return format_html(
                '<a href="{}">{}</a>',
                reverse("admin:posthog_organization_change", args=[team.organization.pk]),
                team.organization.name,
            )
        return "-"

    def project_link(self, team: Team):
        if team.project:
            return format_html(
                '<a href="{}">{}</a>',
                reverse("admin:posthog_project_change", args=[team.project.pk]),
                team.project.name,
            )
        return "-"

    @admin.display(description="PostHog system internal properties")
    def internal_properties(self, team: Team):
        from posthog import settings
        from posthog.rate_limit import team_is_allowed_to_bypass_throttle

        props: list[str] = []
        if settings.API_QUERIES_LEGACY_TEAM_LIST and team.id in settings.API_QUERIES_LEGACY_TEAM_LIST:
            props.append("API_QUERIES_LEGACY_RATE_LIMIT")
        if settings.API_QUERIES_PER_TEAM and team.id in settings.API_QUERIES_PER_TEAM:
            props.append("API_QUERIES_PER_TEAM:{}".format(settings.API_QUERIES_PER_TEAM[team.id]))
        if team_is_allowed_to_bypass_throttle(team.id):
            props.append("API_QUERIES_RATE_LIMIT_BYPASS")
        return format_html("<span>{}</span>", ", ".join(props) or "-")

    @admin.display(description="Export individual session replay data")
    def export_individual_replay(self, team: Team):
        if not team.pk:
            return "-"
        return mark_safe(
            render_to_string(
                "admin/posthog/team/export_individual_replay.html",
                {"team": team},
                request=getattr(self, "_current_request", None),
            )
        )

    @admin.display(description="Import individual session replay data")
    def import_individual_replay(self, team: Team):
        if not team.pk:
            return "-"
        return mark_safe(
            render_to_string(
                "admin/posthog/team/import_individual_replay.html",
                {"team": team},
                request=getattr(self, "_current_request", None),
            )
        )

    @admin.display(description="Remote config cache actions")
    def remote_config_cache_actions(self, team: Team):
        if not team.pk:
            return "-"

        return mark_safe(
            render_to_string(
                "admin/posthog/team/remote_config_cache_actions.html",
                {
                    "view_url": reverse("admin:posthog_team_view_cache", args=[team.pk]),
                    "delete_url": reverse("admin:posthog_team_delete_cache", args=[team.pk]),
                    "team_name_escaped": escapejs(team.name),
                    "cache_key": cache_key_for_team_token(team.api_token),
                },
            )
        )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/view-cache/",
                self.admin_site.admin_view(self.view_cache),
                name="posthog_team_view_cache",
            ),
            path(
                "<path:object_id>/delete-cache/",
                self.admin_site.admin_view(self.delete_cache),
                name="posthog_team_delete_cache",
            ),
            path(
                "<path:object_id>/export-replay/",
                self.admin_site.admin_view(self.export_replay_view),
                name="posthog_team_export_replay",
            ),
            path(
                "<path:object_id>/import-replay/",
                self.admin_site.admin_view(self.import_replay_view),
                name="posthog_team_import_replay",
            ),
        ]
        return custom_urls + urls

    def export_replay_view(self, request, object_id):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        team = Team.objects.get(pk=object_id)
        session_id = request.POST.get("session_id", "").strip()
        reason = request.POST.get("reason", "").strip()

        if not session_id:
            messages.error(request, "Session ID is required")
            return redirect(reverse("admin:posthog_team_change", args=[object_id]))

        if not reason:
            messages.error(request, "Reason is required")
            return redirect(reverse("admin:posthog_team_change", args=[object_id]))

        logger.info(
            "export_replay_triggered",
            team_id=team.id,
            session_id=session_id,
            reason=reason,
            triggered_by=request.user.email,
        )

        messages.success(
            request, f"Export triggered for session '{session_id}' on team '{team.name}' by {request.user.email}"
        )
        return redirect(reverse("admin:posthog_team_change", args=[object_id]))

    def view_cache(self, request, object_id):
        team = Team.objects.get(pk=object_id)
        cache_key = cache_key_for_team_token(team.api_token)
        cached_data = cache.get(cache_key)

        if cached_data == "404":
            return JsonResponse({"error": "Team not found (404 cached)"}, status=404)

        if cached_data is None:
            return JsonResponse({"cached": False, "message": "No cached config found"})

        return JsonResponse(
            {"cached": True, "cache_key": cache_key, "data": cached_data}, json_dumps_params={"indent": 2}
        )

    def delete_cache(self, request, object_id):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        team = Team.objects.get(pk=object_id)
        cache_key = cache_key_for_team_token(team.api_token)
        cache.delete(cache_key)

        self.message_user(request, f"Cache deleted for team '{team.name}' (token: {team.api_token})")
        return redirect(reverse("admin:posthog_team_change", args=[object_id]))

    def import_replay_view(self, request, object_id):
        from posthog.tasks.replay_import import process_replay_import

        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        team = Team.objects.get(pk=object_id)
        reason = request.POST.get("reason", "").strip()
        import_file: UploadedFile | None = request.FILES.get("import_file")

        if not import_file:
            messages.error(request, "Import file is required")
            return redirect(reverse("admin:posthog_team_change", args=[object_id]))

        if not reason:
            messages.error(request, "Reason is required")
            return redirect(reverse("admin:posthog_team_change", args=[object_id]))

        if not import_file.name or not import_file.name.endswith(".zip"):
            messages.error(request, "Import file must be a .zip file")
            return redirect(reverse("admin:posthog_team_change", args=[object_id]))

        logger.info(
            "import_replay_triggered",
            team_id=team.id,
            file_name=import_file.name,
            file_size=import_file.size,
            reason=reason,
            triggered_by=request.user.email,
        )

        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_file:
                for chunk in import_file.chunks():
                    tmp_file.write(chunk)
                tmp_file_path = tmp_file.name

            process_replay_import(team_id=team.id, zip_file_path=tmp_file_path, triggered_by=request.user.email)

            messages.success(
                request,
                f"Import completed for team '{team.name}' by {request.user.email}.",
            )
        except Exception as e:
            logger.exception(
                "import_replay_failed",
                team_id=team.id,
                error=str(e),
            )
            messages.error(request, f"Import failed: {e}")

        return redirect(reverse("admin:posthog_team_change", args=[object_id]))
