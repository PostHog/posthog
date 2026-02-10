import json
import uuid
import asyncio
import tempfile
import dataclasses
from datetime import timedelta

from django.conf import settings
from django.contrib import admin, messages
from django.core.files.uploadedfile import UploadedFile
from django.http import HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import path, reverse
from django.utils.html import escapejs, format_html
from django.utils.safestring import mark_safe

from structlog import get_logger
from temporalio import common

from posthog.admin.inlines.team_marketing_analytics_config_inline import TeamMarketingAnalyticsConfigInline
from posthog.admin.inlines.user_product_list_inline import UserProductListInline
from posthog.cloud_utils import is_cloud
from posthog.models import Team
from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, log_activity
from posthog.models.exported_recording import ExportedRecording
from posthog.models.remote_config import RemoteConfig
from posthog.models.team.team import DEPRECATED_ATTRS
from posthog.storage.recordings import file_storage
from posthog.temporal.common.client import sync_connect
from posthog.temporal.delete_recordings.types import (
    RecordingsWithPersonInput,
    RecordingsWithQueryInput,
    RecordingsWithTeamInput,
)
from posthog.temporal.export_recording.types import ExportRecordingInput
from posthog.temporal.import_recording.types import ImportRecordingInput

logger = get_logger()


@dataclasses.dataclass(frozen=True)
class ReplayActivityContext(ActivityContextBase):
    reason: str


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
        "delete_recordings",
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
                    "proactive_tasks_enabled",
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
                    "delete_recordings",
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
        # nosemgrep: python.django.security.audit.avoid-mark-safe.avoid-mark-safe (admin-only, renders trusted template)
        return mark_safe(
            render_to_string(
                "admin/posthog/team/export_individual_replay.html",
                {
                    "team": team,
                    "export_url": f"/admin/posthog/team/{team.pk}/export-replay/",
                    "export_history_url": f"/admin/posthog/team/{team.pk}/export-history/",
                },
                request=getattr(self, "_current_request", None),
            )
        )

    @admin.display(description="Import individual session replay data")
    def import_individual_replay(self, team: Team):
        if not team.pk:
            return "-"
        # nosemgrep: python.django.security.audit.avoid-mark-safe.avoid-mark-safe (admin-only, renders trusted template)
        return mark_safe(
            render_to_string(
                "admin/posthog/team/import_individual_replay.html",
                {
                    "team": team,
                    "import_url": f"/admin/posthog/team/{team.pk}/import-replay/",
                },
                request=getattr(self, "_current_request", None),
            )
        )

    @admin.display(description="Delete recordings")
    def delete_recordings(self, team: Team):
        if not team.pk:
            return "-"
        delete_url = reverse("admin:posthog_team_delete_recordings", args=[team.pk])
        return format_html(
            '<a class="button" href="{}">Manage recording deletion</a>',
            delete_url,
        )

    @admin.display(description="Remote config cache actions")
    def remote_config_cache_actions(self, team: Team):
        if not team.pk:
            return "-"

        # nosemgrep: python.django.security.audit.avoid-mark-safe.avoid-mark-safe (admin-only, renders trusted template)
        return mark_safe(
            render_to_string(
                "admin/posthog/team/remote_config_cache_actions.html",
                {
                    "view_url": reverse("admin:posthog_team_view_cache", args=[team.pk]),
                    "rebuild_url": reverse("admin:posthog_team_rebuild_cache", args=[team.pk]),
                    "team_name_escaped": escapejs(team.name),
                    "cache_key": RemoteConfig.get_hypercache().get_cache_key(team.api_token),
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
                "<path:object_id>/rebuild-cache/",
                self.admin_site.admin_view(self.rebuild_cache),
                name="posthog_team_rebuild_cache",
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
            path(
                "<path:object_id>/export-history/",
                self.admin_site.admin_view(self.export_history_view),
                name="posthog_team_export_history",
            ),
            path(
                "<path:object_id>/download-export/<uuid:export_id>/",
                self.admin_site.admin_view(self.download_export_view),
                name="posthog_team_download_export",
            ),
            path(
                "<path:object_id>/delete-recordings/",
                self.admin_site.admin_view(self.delete_recordings_view),
                name="posthog_team_delete_recordings",
            ),
            path(
                "<path:object_id>/delete-recordings/certificate/<str:workflow_id>/",
                self.admin_site.admin_view(self.deletion_certificate_view),
                name="posthog_team_deletion_certificate",
            ),
            path(
                "<path:object_id>/delete-recordings/certificate/<str:workflow_id>/download/",
                self.admin_site.admin_view(self.download_deletion_certificate_view),
                name="posthog_team_download_deletion_certificate",
            ),
        ]
        return custom_urls + urls

    def export_replay_view(self, request, object_id):
        team = Team.objects.get(pk=object_id)

        if request.method == "GET":
            context = {
                **self.admin_site.each_context(request),
                "team": team,
                "title": f"Export Session Replay - {team.name}",
            }
            return render(request, "admin/posthog/team/export_replay_form.html", context)

        session_id = request.POST.get("session_id", "").strip()
        reason = request.POST.get("reason", "").strip()

        if not session_id:
            messages.error(request, "Session ID is required")
            return redirect(reverse("admin:posthog_team_export_replay", args=[object_id]))

        if not reason:
            messages.error(request, "Reason is required")
            return redirect(reverse("admin:posthog_team_export_replay", args=[object_id]))

        logger.info(
            "export_replay_triggered",
            team_id=team.id,
            session_id=session_id,
            reason=reason,
            triggered_by=request.user.email,
        )

        export_record = ExportedRecording.objects.create(
            team=team,
            session_id=session_id,
            reason=reason,
            created_by=request.user,
        )

        try:
            temporal = sync_connect()
            workflow_input = ExportRecordingInput(exported_recording_id=export_record.id)
            workflow_id = f"export-recording-{export_record.id}-{uuid.uuid4()}"

            asyncio.run(
                temporal.start_workflow(
                    "export-recording",
                    workflow_input,
                    id=workflow_id,
                    task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
                    retry_policy=common.RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(minutes=1),
                    ),
                )
            )

            log_activity(
                organization_id=team.organization_id,
                team_id=team.id,
                user=request.user,
                was_impersonated=False,
                item_id=session_id,
                scope="Replay",
                activity="exported",
                detail=Detail(
                    name=f"Session replay {session_id}",
                    short_id=session_id,
                    type="admin_export",
                    context=ReplayActivityContext(reason=reason),
                ),
            )

            messages.success(
                request,
                f"Export triggered for session '{session_id}' on team '{team.name}' by {request.user.email}. Export ID: {export_record.id}",
            )
        except Exception as e:
            logger.exception(
                "export_replay_failed",
                team_id=team.id,
                session_id=session_id,
                error=str(e),
            )
            messages.error(request, f"Export failed: {e}")

        return redirect(reverse("admin:posthog_team_export_history", args=[object_id]))

    def view_cache(self, request, object_id):
        team = Team.objects.get(pk=object_id)
        hypercache = RemoteConfig.get_hypercache()
        cache_key = hypercache.get_cache_key(team.api_token)

        # source tells us where the result came from ("redis", "s3", or None).
        # When data is None, source disambiguates: a cache hit returning None means
        # the team was explicitly cached as missing, while no source means a true cache miss.
        cached_data, source = hypercache.get_from_cache_with_source(team.api_token)

        if cached_data is None:
            if source in ("redis", "s3"):
                return JsonResponse({"cached": True, "cache_key": cache_key, "message": "Team cached as missing"})
            return JsonResponse({"cached": False, "message": "No cached config found"})

        return JsonResponse(
            {"cached": True, "cache_key": cache_key, "data": cached_data}, json_dumps_params={"indent": 2}
        )

    def rebuild_cache(self, request, object_id):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        team = Team.objects.get(pk=object_id)
        RemoteConfig.get_hypercache().update_cache(team.api_token)

        self.message_user(request, f"Cache rebuilt for team '{team.name}' (token: {team.api_token})")
        return redirect(reverse("admin:posthog_team_change", args=[object_id]))

    def import_replay_view(self, request, object_id):
        if is_cloud():
            messages.error(request, "Importing session replays is not allowed on cloud")
            return redirect(reverse("admin:posthog_team_change", args=[object_id]))

        team = Team.objects.get(pk=object_id)

        if request.method == "GET":
            context = {
                **self.admin_site.each_context(request),
                "team": team,
                "title": f"Import Session Replay - {team.name}",
            }
            return render(request, "admin/posthog/team/import_replay_form.html", context)

        reason = request.POST.get("reason", "").strip()
        import_file: UploadedFile | None = request.FILES.get("import_file")

        if not import_file:
            messages.error(request, "Import file is required")
            return redirect(reverse("admin:posthog_team_import_replay", args=[object_id]))

        if not reason:
            messages.error(request, "Reason is required")
            return redirect(reverse("admin:posthog_team_import_replay", args=[object_id]))

        if not import_file.name or not import_file.name.endswith(".zip"):
            messages.error(request, "Import file must be a .zip file")
            return redirect(reverse("admin:posthog_team_import_replay", args=[object_id]))

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

            temporal = sync_connect()
            workflow_input = ImportRecordingInput(team_id=team.id, export_file=tmp_file_path)
            workflow_id = f"import-recording-{team.id}-{uuid.uuid4()}"

            asyncio.run(
                temporal.start_workflow(
                    "import-recording",
                    workflow_input,
                    id=workflow_id,
                    task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
                    retry_policy=common.RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(minutes=1),
                    ),
                )
            )

            log_activity(
                organization_id=team.organization_id,
                team_id=team.id,
                user=request.user,
                was_impersonated=False,
                item_id=None,
                scope="Replay",
                activity="imported",
                detail=Detail(
                    name=f"Session replay import from {import_file.name}",
                    type="admin_import",
                    context=ReplayActivityContext(reason=reason),
                ),
            )

            messages.success(
                request,
                f"Import triggered for team '{team.name}' by {request.user.email}.",
            )
        except Exception as e:
            logger.exception(
                "import_replay_failed",
                team_id=team.id,
                error=str(e),
            )
            messages.error(request, f"Import failed: {e}")

        return redirect(reverse("admin:posthog_team_export_history", args=[object_id]))

    def export_history_view(self, request, object_id):
        team = Team.objects.get(pk=object_id)

        exports = ExportedRecording.objects.filter(team=team).order_by("-created_at")[:50]

        context = {
            **self.admin_site.each_context(request),
            "team": team,
            "exports": exports,
            "title": f"Export History - {team.name}",
        }
        return render(request, "admin/posthog/team/export_history.html", context)

    def download_export_view(self, request, object_id, export_id):
        team = Team.objects.get(pk=object_id)
        try:
            export = ExportedRecording.objects.get(id=export_id, team=team)

            if not export.export_location:
                messages.error(request, "Export content not available yet")
                return redirect(reverse("admin:posthog_team_export_history", args=[object_id]))

            content = file_storage.file_storage().download_file(export.export_location)

            response = HttpResponse(content, content_type="application/zip")
            filename = f"export-{export.session_id}.zip"
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response

        except ExportedRecording.DoesNotExist:
            messages.error(request, "Export not found")
            return redirect(reverse("admin:posthog_team_export_history", args=[object_id]))
        except Exception as e:
            messages.error(request, f"Failed to download export: {e}")
            return redirect(reverse("admin:posthog_team_export_history", args=[object_id]))

    def _get_delete_workflows(self, team_id: int) -> list[dict]:
        """Fetch recent delete-recordings workflows for this team from Temporal."""
        try:
            temporal = sync_connect()
            query = f'WorkflowId STARTS_WITH "delete-recordings-{team_id}-"'

            async def fetch_workflows():
                workflows = []
                async for wf in temporal.list_workflows(query=query):
                    workflows.append(
                        {
                            "id": wf.id,
                            "run_id": wf.run_id,
                            "status": str(wf.status.name) if wf.status else "Unknown",
                            "start_time": wf.start_time,
                            "close_time": wf.close_time,
                            "workflow_type": wf.workflow_type,
                        }
                    )
                    if len(workflows) >= 20:
                        break
                return workflows

            return asyncio.run(fetch_workflows())
        except Exception as e:
            logger.warning("Failed to fetch delete workflows", error=str(e))
            return []

    def delete_recordings_view(self, request, object_id):
        team = Team.objects.get(pk=object_id)

        if request.method == "GET":
            workflows = self._get_delete_workflows(team.id)
            context = {
                **self.admin_site.each_context(request),
                "team": team,
                "title": f"Delete Recordings - {team.name}",
                "workflows": workflows,
            }
            return render(request, "admin/posthog/team/delete_recordings.html", context)

        workflow_type = request.POST.get("workflow_type", "").strip()
        reason = request.POST.get("reason", "").strip()
        dry_run = request.POST.get("dry_run") == "on"

        if not reason:
            messages.error(request, "Reason is required")
            return redirect(reverse("admin:posthog_team_delete_recordings", args=[object_id]))

        try:
            temporal = sync_connect()
            workflow_id = f"delete-recordings-{team.id}-{uuid.uuid4()}"

            if workflow_type == "person":
                distinct_ids_raw = request.POST.get("distinct_ids", "").strip()
                if not distinct_ids_raw:
                    messages.error(request, "Distinct IDs are required for person-based deletion")
                    return redirect(reverse("admin:posthog_team_delete_recordings", args=[object_id]))

                distinct_ids = [d.strip() for d in distinct_ids_raw.split("\n") if d.strip()]
                workflow_input = RecordingsWithPersonInput(team_id=team.id, distinct_ids=distinct_ids)

                asyncio.run(
                    temporal.start_workflow(
                        "delete-recordings-with-person",
                        workflow_input,
                        id=workflow_id,
                        task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
                        retry_policy=common.RetryPolicy(
                            maximum_attempts=2,
                            initial_interval=timedelta(minutes=1),
                        ),
                    )
                )

                logger.info(
                    "delete_recordings_with_person_triggered",
                    team_id=team.id,
                    distinct_ids_count=len(distinct_ids),
                    reason=reason,
                    triggered_by=request.user.email,
                )

                messages.success(
                    request,
                    f"Delete recordings workflow triggered for {len(distinct_ids)} distinct ID(s). Workflow ID: {workflow_id}",
                )

            elif workflow_type == "team":
                workflow_input = RecordingsWithTeamInput(team_id=team.id, dry_run=dry_run)

                asyncio.run(
                    temporal.start_workflow(
                        "delete-recordings-with-team",
                        workflow_input,
                        id=workflow_id,
                        task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
                        retry_policy=common.RetryPolicy(
                            maximum_attempts=2,
                            initial_interval=timedelta(minutes=1),
                        ),
                    )
                )

                logger.info(
                    "delete_recordings_with_team_triggered",
                    team_id=team.id,
                    dry_run=dry_run,
                    reason=reason,
                    triggered_by=request.user.email,
                )

                dry_run_msg = " (DRY RUN)" if dry_run else ""
                messages.success(
                    request,
                    f"Delete all recordings workflow triggered for team{dry_run_msg}. Workflow ID: {workflow_id}",
                )

            elif workflow_type == "filters":
                query_parts = []

                date_from = request.POST.get("date_from", "").strip()
                date_to = request.POST.get("date_to", "").strip()
                duration_min = request.POST.get("duration_min", "").strip()
                duration_max = request.POST.get("duration_max", "").strip()
                person_uuid = request.POST.get("person_uuid", "").strip()
                platform = request.POST.get("platform", "").strip()

                has_filter = any([date_from, date_to, duration_min, duration_max, person_uuid, platform])
                if not has_filter:
                    messages.error(request, "At least one filter is required for filter-based deletion")
                    return redirect(reverse("admin:posthog_team_delete_recordings", args=[object_id]))

                if date_from:
                    query_parts.append(f"date_from={date_from}")
                if date_to:
                    query_parts.append(f"date_to={date_to}")
                if person_uuid:
                    query_parts.append(f"person_uuid={person_uuid}")

                properties = []
                if duration_min:
                    properties.append(
                        {
                            "type": "recording",
                            "key": "duration",
                            "operator": "gt",
                            "value": int(duration_min),
                        }
                    )
                if duration_max:
                    properties.append(
                        {
                            "type": "recording",
                            "key": "duration",
                            "operator": "lt",
                            "value": int(duration_max),
                        }
                    )
                if platform:
                    properties.append(
                        {
                            "type": "recording",
                            "key": "snapshot_source",
                            "operator": "exact",
                            "value": [platform],
                        }
                    )
                if properties:
                    query_parts.append(f"properties={json.dumps(properties)}")

                query = "&".join(query_parts)
                workflow_input = RecordingsWithQueryInput(team_id=team.id, query=query, dry_run=dry_run)

                asyncio.run(
                    temporal.start_workflow(
                        "delete-recordings-with-query",
                        workflow_input,
                        id=workflow_id,
                        task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
                        retry_policy=common.RetryPolicy(
                            maximum_attempts=2,
                            initial_interval=timedelta(minutes=1),
                        ),
                    )
                )

                logger.info(
                    "delete_recordings_with_filters_triggered",
                    team_id=team.id,
                    query=query,
                    dry_run=dry_run,
                    reason=reason,
                    triggered_by=request.user.email,
                )

                dry_run_msg = " (DRY RUN)" if dry_run else ""
                messages.success(
                    request,
                    f"Delete recordings by filters workflow triggered{dry_run_msg}. Workflow ID: {workflow_id}",
                )

            else:
                messages.error(request, "Invalid workflow type")
                return redirect(reverse("admin:posthog_team_delete_recordings", args=[object_id]))

            log_activity(
                organization_id=team.organization_id,
                team_id=team.id,
                user=request.user,
                was_impersonated=False,
                item_id=workflow_id,
                scope="Replay",
                activity="bulk_delete_triggered",
                detail=Detail(
                    name=f"Bulk delete recordings ({workflow_type})",
                    type=f"admin_delete_{workflow_type}",
                    context=ReplayActivityContext(reason=reason),
                ),
            )

        except Exception as e:
            logger.exception(
                "delete_recordings_failed",
                team_id=team.id,
                workflow_type=workflow_type,
                error=str(e),
            )
            messages.error(request, f"Failed to trigger workflow: {e}")

        return redirect(reverse("admin:posthog_team_delete_recordings", args=[object_id]))

    def _get_deletion_certificate(self, team_id: int, workflow_id: str):
        """Fetch a deletion certificate from a completed Temporal workflow."""
        if not workflow_id.startswith(f"delete-recordings-{team_id}-"):
            return None, "Invalid workflow ID for this team"

        try:
            temporal = sync_connect()

            async def get_result():
                handle = temporal.get_workflow_handle(workflow_id)
                return await handle.result()

            certificate = asyncio.run(get_result())
            return certificate, None
        except Exception as e:
            logger.warning("Failed to fetch deletion certificate", workflow_id=workflow_id, error=str(e))
            return None, str(e)

    def deletion_certificate_view(self, request, object_id, workflow_id):
        """Display a deletion certificate as a printable HTML page."""
        team = Team.objects.get(pk=object_id)

        certificate, error = self._get_deletion_certificate(team.id, workflow_id)
        if error:
            messages.error(request, f"Failed to fetch certificate: {error}")
            return redirect(reverse("admin:posthog_team_delete_recordings", args=[object_id]))

        context = {
            **self.admin_site.each_context(request),
            "team": team,
            "certificate": certificate,
            "title": f"Deletion Certificate - {workflow_id}",
        }
        return render(request, "admin/posthog/team/deletion_certificate.html", context)

    def download_deletion_certificate_view(self, request, object_id, workflow_id):
        """Download a deletion certificate as JSON."""
        team = Team.objects.get(pk=object_id)

        certificate, error = self._get_deletion_certificate(team.id, workflow_id)
        if error:
            messages.error(request, f"Failed to fetch certificate: {error}")
            return redirect(reverse("admin:posthog_team_delete_recordings", args=[object_id]))

        response = HttpResponse(
            certificate.model_dump_json(indent=2),
            content_type="application/json",
        )
        filename = f"deletion-certificate-{workflow_id}.json"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
