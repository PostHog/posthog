import io
import csv
import json
import uuid
import asyncio
import dataclasses
from datetime import datetime, timedelta
from urllib import parse

from django.conf import settings
from django.contrib import admin, messages
from django.core.files.uploadedfile import UploadedFile
from django.forms import ModelForm, ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from structlog import get_logger
from temporalio import common
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import SearchAttributePair, TypedSearchAttributes

from posthog.admin.console.moved import MovedToConsole
from posthog.admin.inline_registry import extra_inlines_for
from posthog.admin.inlines.events_retention_config_inline import TeamEventsRetentionConfigInline
from posthog.admin.inlines.organization_member_for_related_inline import OrganizationMemberForRelatedInline
from posthog.admin.inlines.team_marketing_analytics_config_inline import TeamMarketingAnalyticsConfigInline
from posthog.models import Team
from posthog.models.activity_logging.activity_log import ActivityContextBase, ActivityLog, Detail, log_activity
from posthog.models.events_retention_config import (
    OrganizationEventsRetentionConfig,
    TeamEventsRetentionConfig,
    describe_months_range,
)
from posthog.models.team.event_retention import should_enforce_events_retention
from posthog.models.team.team import DEPRECATED_ATTRS
from posthog.storage.gateway_credential_cache import validate_overspend_allowance_usd
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.search_attributes import POSTHOG_TEAM_ID_KEY
from posthog.temporal.session_replay.delete_recordings.object_storage import store_session_id_chunks
from posthog.temporal.session_replay.delete_recordings.types import (
    DeletionConfig,
    RecordingsWithPersonInput,
    RecordingsWithQueryInput,
    RecordingsWithSessionIdsInput,
    RecordingsWithTeamInput,
)

from products.workflows.backend.facade.api import (
    get_email_sending_state,
    get_email_sending_tier_limits,
    max_email_sending_tier,
)

logger = get_logger()


@dataclasses.dataclass(frozen=True)
class ReplayActivityContext(ActivityContextBase):
    reason: str


class TeamAdminForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["test_account_filters"].required = False
        self.fields["test_account_filters"].help_text = "list: Default value is an empty `[]`"

    def clean_test_account_filters(self):
        value = self.cleaned_data.get("test_account_filters")
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValidationError("test_account_filters must be a JSON list (e.g. `[]`).")
        return value

    def clean_llm_gateway_overspend_allowance_usd(self):
        value = self.cleaned_data.get("llm_gateway_overspend_allowance_usd")
        if value is None:
            return value
        # The projection reads the allowance from the project-root team, so a child-env value
        # never reaches the wire — reject instead of silently no-opping.
        if self.instance.parent_team_id is not None:
            raise ValidationError(
                f"This is a child environment; set the allowance on its project-root team "
                f"({self.instance.parent_team_id}) instead."
            )
        try:
            return validate_overspend_allowance_usd(value)
        except ValueError as e:
            raise ValidationError(str(e))


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    form = TeamAdminForm

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
        "created_at",
        "updated_at",
        "internal_properties",
        "remote_config_cache_actions",
        "flags_staff_tools_link",
        "delete_recordings",
        "api_token_display",
        "admit_state",
        "ai_gateway_actions",
        "ai_gateway_wallet",
        "ai_gateway_credit_history",
        "policy_cache_blob",
        "group_type_mappings_display",
        "email_sending_suspension_state",
        "email_sending_suspension_actions",
        "email_sending_tier_state",
        "email_sending_tier_actions",
        "events_retention_display",
    ]

    exclude = DEPRECATED_ATTRS
    inlines = [
        OrganizationMemberForRelatedInline,
        TeamMarketingAnalyticsConfigInline,
        TeamEventsRetentionConfigInline,
    ]

    def get_inlines(self, request, obj=None):
        # Inlines other apps registered for Team, so a product can show a panel on
        # this page without core importing it. See posthog.admin.inline_registry.
        return [*super().get_inlines(request, obj), *extra_inlines_for(Team)]

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
                    "flags_staff_tools_link",
                ],
            },
        ),
        (
            "General",
            {
                "classes": ["collapse"],
                "fields": [
                    "api_token_display",
                    "timezone",
                    "week_start_day",
                    "base_currency",
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
            "Events retention",
            {
                "classes": ["collapse"],
                "fields": [
                    "events_retention_display",
                ],
            },
        ),
        (
            "Group type mappings",
            {
                "classes": ["collapse"],
                "fields": [
                    "group_type_mappings_display",
                ],
            },
        ),
        (
            "Session replay actions",
            {
                "classes": ["collapse"],
                "fields": [
                    "delete_recordings",
                ],
            },
        ),
        (
            "AI Gateway",
            {
                "classes": ["collapse"],
                "fields": [
                    "llm_gateway_enabled_at",
                    "llm_gateway_revoked_at",
                    "llm_gateway_overspend_allowance_usd",
                    "admit_state",
                    "ai_gateway_actions",
                    "ai_gateway_wallet",
                    "ai_gateway_credit_history",
                    "policy_cache_blob",
                ],
                "description": mark_safe(
                    "<strong>Per-region change.</strong> Applies to the current region only. "
                    "If you want the team enabled or revoked in the other region too, flip the "
                    "matching Team row there. The gateway admits a team only when "
                    "<code>llm_gateway_enabled_at</code> is set and "
                    "<code>llm_gateway_revoked_at</code> is null. "
                    "<code>llm_gateway_overspend_allowance_usd</code> (0–10000) lets the team keep dispatching "
                    "past $0 down to that USD floor; leave blank to use the gateway's operator default."
                ),
            },
        ),
        (
            "Workflow email sending",
            {
                "classes": ["collapse"],
                "fields": [
                    "email_sending_suspension_state",
                    "email_sending_suspension_actions",
                    "email_sending_tier_state",
                    "email_sending_tier_actions",
                ],
                "description": mark_safe(
                    "Kill switch for all workflow email from this team, used when its sender reputation "
                    "(hard bounce / spam complaint rates) endangers shared SES deliverability. Suspending "
                    "notifies the team by email and in-app; the CDP email worker picks the flag up within "
                    "a few minutes.<br><br>The trust tier below sets how fast this team may send. Teams "
                    "earn tiers automatically by sending cleanly over time; pinning holds a team at a tier "
                    "and stops both automatic promotion and automatic demotion."
                ),
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

    @admin.display(description="Group type mappings")
    def group_type_mappings_display(self, team: Team):
        if not team.pk:
            return "-"
        return MovedToConsole.team_action(team, "group-types", "View and edit group types")

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

    @admin.display(description="Events retention")
    def events_retention_display(self, team: Team):
        if not team.pk:
            return "-"
        team_months = (
            TeamEventsRetentionConfig.objects.filter(team_id=team.pk)
            .values_list("events_retention_months", flat=True)
            .first()
        )
        org_config = OrganizationEventsRetentionConfig.objects.filter(organization_id=team.organization_id).first()
        org_default = org_config.default_events_retention_months if org_config else None
        if team_months is not None:
            deletion = f"Deleted after {team_months} months, from the team setting."
        elif org_default is not None:
            deletion = f"Deleted after {org_default} months, from the organization default."
        else:
            deletion = "Never deleted. Neither the team nor the organization has a setting."
        if org_config and (org_config.min_events_retention_months or org_config.max_events_retention_months):
            allowed = describe_months_range(
                org_config.min_events_retention_months, org_config.max_events_retention_months
            )
            deletion += f" The organization allows {allowed}."

        hidden = (
            "Older events are hidden from queries."
            if should_enforce_events_retention(team.pk)
            else "Older events are not hidden yet, because enforcement is off for this team."
        )
        billing = f"{team.event_retention_months} months from the billing plan. {hidden}"
        return format_html("<div>{}</div><div>{}</div>", deletion, billing)

    @admin.display(description="API token")
    def api_token_display(self, team: Team):
        if not team.pk:
            return "-"
        return format_html(
            "<span>{}</span> &nbsp; {}",
            team.api_token,
            MovedToConsole.team_action(team, "api-token", "Set API token"),
        )

    @admin.display(description="Delete recordings")
    def delete_recordings(self, team: Team):
        if not team.pk:
            return "-"
        delete_url = reverse("admin:posthog_team_delete_recordings", args=[team.pk])
        return format_html(
            '<a class="button" href="{}">Delete recordings</a>',
            delete_url,
        )

    @admin.display(description="Flags staff tools")
    def flags_staff_tools_link(self, team: Team):
        # Mirrors urls.featureFlagsStaffTools() in products/feature_flags/manifest.tsx; keep in sync.
        if not team.pk:
            return "-"
        return format_html(
            '<a class="button" href="/feature-flags/staff?team_id={}" target="_blank" rel="noopener noreferrer">Open flags staff tools</a>',
            team.pk,
        )

    @admin.display(description="Remote config cache actions")
    def remote_config_cache_actions(self, team: Team):
        if not team.pk:
            return "-"
        return MovedToConsole.team_action(team, "remote-config", "View and rebuild cache")

    @admin.display(description="Email sending state")
    def email_sending_suspension_state(self, team: Team):
        if not team.pk:
            return "-"
        state = get_email_sending_state(team.pk)
        if state and state.suspended_at:
            return format_html(
                '<span style="color:red"><strong>Suspended</strong></span> at {} — {}',
                state.suspended_at.isoformat(),
                state.suspension_reason or "no reason recorded",
            )
        return mark_safe("<em>Sending enabled</em>")

    @admin.display(description="Email sending actions")
    def email_sending_suspension_actions(self, team: Team):
        if not team.pk:
            return "-"
        return MovedToConsole.team_action(team, "email-sending", "Suspending and re-enabling email sending")

    @admin.display(description="Email sending tier")
    def email_sending_tier_state(self, team: Team) -> str:
        if not team.pk:
            return "-"
        state = get_email_sending_state(team.pk)
        tier = state.tier if state else 0
        limits = get_email_sending_tier_limits(tier)
        updated_at = state.tier_updated_at if state else None
        allowlist_note = ""
        if team.pk in settings.HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS:
            # A saved tier changes nothing while the team sits on the legacy allowlist, which the
            # limit resolution checks first. Say so here rather than letting a staff tier write
            # look effective when it is not.
            allowlist_note = (
                "<br><strong>Note:</strong> this team is on the legacy elevated allowlist "
                "(HOGFLOW_BATCH_TRIGGER_ELEVATED_TEAM_IDS), which overrides the tier until the "
                "team is removed from it."
            )
        return format_html(
            "<strong>Tier {}</strong> of {} — {} emails/day, "
            "{} max batch audience<br>Set at: {}<br>Pinned: {}<br>Rollout mode: <code>{}</code>{}",
            tier,
            max_email_sending_tier(),
            f"{limits.per_day:,}",
            f"{limits.max_batch_audience:,}",
            updated_at.isoformat() if updated_at else "never (team has not been evaluated yet)",
            "yes" if state and state.tier_pinned else "no",
            settings.WORKFLOWS_EMAIL_TIER_MODE,
            mark_safe(allowlist_note),  # noqa: S308 - static admin-only string, no user input
        )

    @admin.display(description="Email sending tier actions")
    def email_sending_tier_actions(self, team: Team) -> str:
        if not team.pk:
            return "-"
        return MovedToConsole.team_action(team, "email-sending", "Setting and recomputing the tier")

    @admin.display(description="Actions")
    def ai_gateway_actions(self, team: Team):
        if not team.pk:
            return "-"
        return MovedToConsole.team_action(team, "ai-gateway", "Enabling and revoking access")

    @admin.display(description="Admit state")
    def admit_state(self, team: Team):
        if not team.pk:
            return "-"
        if team.llm_gateway_revoked_at:
            return format_html(
                '<span style="color:red"><strong>Revoked</strong></span> at {}',
                team.llm_gateway_revoked_at.isoformat(),
            )
        if team.llm_gateway_enabled_at:
            return format_html(
                '<span style="color:green"><strong>Enrolled</strong></span> since {}',
                team.llm_gateway_enabled_at.isoformat(),
            )
        return mark_safe("<em>Not enrolled</em>")

    @admin.display(description="Wallet (AI gateway credits)")
    def ai_gateway_wallet(self, team: Team):
        if not team.pk:
            return "-"
        return MovedToConsole.team_action(team, "ai-gateway", "Wallet balance, ledger and Add credit")

    @admin.display(description="Recent top-ups (who topped up)")
    def ai_gateway_credit_history(self, team: Team):
        if not team.pk:
            return "-"
        # Local ActivityLog read (no gateway call), so render inline. The ledger
        # records the movement; the actor lives here, joined by item_id == entry_id.
        entries = (
            ActivityLog.objects.filter(scope="AIGatewayCredit", team_id=team.pk, activity="credit_added")
            .select_related("user")
            .order_by("-created_at")[:20]
        )
        if not entries:
            return mark_safe("<em>(no top-ups recorded)</em>")
        rows = format_html_join(
            "",
            "<tr><td>{}</td><td>{}</td><td>${}</td><td>{}</td></tr>",
            (
                (
                    e.created_at.strftime("%Y-%m-%d %H:%M UTC"),
                    format_html(
                        "{}{}", e.user.email if e.user else "—", " (impersonated)" if e.was_impersonated else ""
                    ),
                    (e.detail or {}).get("context", {}).get("amount_usd", ""),
                    (e.detail or {}).get("context", {}).get("reason", ""),
                )
                for e in entries
            ),
        )
        return format_html(
            "<table><thead><tr><th>When</th><th>Who</th><th>Amount</th><th>Reason</th></tr></thead>"
            "<tbody>{}</tbody></table>",
            rows,
        )

    @admin.display(description="Policy cache blob (what the gateway sees)")
    def policy_cache_blob(self, team: Team):
        if not team.pk:
            return "-"
        from posthog.storage.team_llm_gateway_policy_cache import get_team_llm_gateway_policy_from_redis

        try:
            blob, source = get_team_llm_gateway_policy_from_redis(team)
        except Exception as exc:
            return format_html("<em>(cache read failed: {})</em>", str(exc))
        if source == "absent":
            return mark_safe("<em>(no entry in Redis for this team; gateway denies until something writes one)</em>")
        if source == "redis_negative":
            return mark_safe(
                "<em>(negative-cache sentinel in Redis; gateway treats as default-deny "
                "until the entry expires, default 24h)</em>"
            )
        return format_html("<pre>{}</pre>", json.dumps(blob, indent=2, default=str))

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
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
            path(
                "<path:object_id>/delete-recordings/workflows/",
                self.admin_site.admin_view(self.delete_recordings_workflows_fragment),
                name="posthog_team_delete_recordings_workflows",
            ),
        ]
        return custom_urls + urls

    def _get_delete_workflows(self, team_id: int) -> list[dict]:
        """Fetch recent delete-recordings workflows for this team from Temporal."""
        try:
            temporal = sync_connect()
            # Use the PostHogTeamId search attribute (indexed) instead of WorkflowId range scan.
            # WorkflowId range queries (>=, <) are not efficiently indexed and cause 30s+ timeouts.
            workflow_types = [
                "delete-recordings-with-person",
                "delete-recordings-with-team",
                "delete-recordings-with-query",
                "delete-recordings-with-session-ids",
            ]
            type_clauses = " OR ".join(f'WorkflowType = "{wt}"' for wt in workflow_types)
            query = f"PostHogTeamId = {team_id} AND ({type_clauses})"

            async def fetch_workflows():
                workflows = []
                async for wf in temporal.list_workflows(query=query, rpc_timeout=timedelta(seconds=5)):
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

    def delete_recordings_workflows_fragment(self, request, object_id):
        """Return just the workflow table rows as an HTML fragment for AJAX polling."""
        team = Team.objects.get(pk=object_id)
        workflows = self._get_delete_workflows(team.id)
        context = {
            "team": team,
            "workflows": workflows,
            "temporal_ui_host": settings.TEMPORAL_UI_HOST,
            "temporal_namespace": settings.TEMPORAL_NAMESPACE,
        }
        return render(request, "admin/posthog/team/_delete_recordings_workflows.html", context)

    def delete_recordings_view(self, request, object_id):
        team = Team.objects.get(pk=object_id)

        if request.method == "GET":
            workflows = self._get_delete_workflows(team.id)
            context = {
                **self.admin_site.each_context(request),
                "team": team,
                "title": f"Delete Recordings - {team.name}",
                "workflows": workflows,
                "temporal_ui_host": settings.TEMPORAL_UI_HOST,
                "temporal_namespace": settings.TEMPORAL_NAMESPACE,
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
            config = DeletionConfig(reason=reason, dry_run=dry_run, deleted_by=request.user.email)
            team_search_attrs = TypedSearchAttributes(
                search_attributes=[SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=team.id)]
            )

            if workflow_type == "person":
                distinct_ids_raw = request.POST.get("distinct_ids", "").strip()
                if not distinct_ids_raw:
                    messages.error(request, "Distinct IDs are required for person-based deletion")
                    return redirect(reverse("admin:posthog_team_delete_recordings", args=[object_id]))

                distinct_ids = [d.strip() for d in distinct_ids_raw.split("\n") if d.strip()]
                person_input = RecordingsWithPersonInput(team_id=team.id, distinct_ids=distinct_ids, config=config)

                asyncio.run(
                    temporal.start_workflow(
                        "delete-recordings-with-person",
                        person_input,
                        id=workflow_id,
                        task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
                        retry_policy=common.RetryPolicy(
                            maximum_attempts=2,
                            initial_interval=timedelta(minutes=1),
                        ),
                        search_attributes=team_search_attrs,
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
                team_input = RecordingsWithTeamInput(team_id=team.id, config=config)

                asyncio.run(
                    temporal.start_workflow(
                        "delete-recordings-with-team",
                        team_input,
                        id=workflow_id,
                        task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
                        retry_policy=common.RetryPolicy(
                            maximum_attempts=2,
                            initial_interval=timedelta(minutes=1),
                        ),
                        search_attributes=team_search_attrs,
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

                # Relative dates need a "d" suffix (e.g. "-360d") — bare integers
                # like "-360" get parsed as ints by query_as_params_to_dict and
                # fail Pydantic validation downstream.
                if date_from.lstrip("-").isdigit():
                    date_from = f"{date_from}d"
                if date_to.lstrip("-").isdigit():
                    date_to = f"{date_to}d"
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
                    try:
                        duration_min_val = int(duration_min)
                    except ValueError:
                        messages.error(request, "Min duration must be a number (in seconds)")
                        return redirect(reverse("admin:posthog_team_delete_recordings", args=[object_id]))
                    properties.append(
                        {
                            "type": "recording",
                            "key": "duration",
                            "operator": "gt",
                            "value": duration_min_val,
                        }
                    )
                if duration_max:
                    try:
                        duration_max_val = int(duration_max)
                    except ValueError:
                        messages.error(request, "Max duration must be a number (in seconds)")
                        return redirect(reverse("admin:posthog_team_delete_recordings", args=[object_id]))
                    properties.append(
                        {
                            "type": "recording",
                            "key": "duration",
                            "operator": "lt",
                            "value": duration_max_val,
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
                    query_parts.append(f"having_predicates={json.dumps(properties)}")

                query = "&".join(query_parts)
                query_input = RecordingsWithQueryInput(team_id=team.id, query=query, config=config)

                asyncio.run(
                    temporal.start_workflow(
                        "delete-recordings-with-query",
                        query_input,
                        id=workflow_id,
                        task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
                        retry_policy=common.RetryPolicy(
                            maximum_attempts=2,
                            initial_interval=timedelta(minutes=1),
                        ),
                        search_attributes=team_search_attrs,
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

            elif workflow_type == "session_ids":
                upload_file: UploadedFile | None = request.FILES.get("session_ids_file")
                if not upload_file:
                    messages.error(request, "CSV file is required for session ID-based deletion")
                    return redirect(reverse("admin:posthog_team_delete_recordings", args=[object_id]))

                if not upload_file.name or not upload_file.name.endswith(".csv"):
                    messages.error(request, "File must be a .csv file")
                    return redirect(reverse("admin:posthog_team_delete_recordings", args=[object_id]))

                content = upload_file.read().decode("utf-8")
                reader = csv.reader(io.StringIO(content))
                session_ids: list[str] = []
                for row in reader:
                    if not row:
                        continue
                    value = row[0].strip()
                    if value and value.lower() != "session_id":
                        session_ids.append(value)

                session_ids = list(dict.fromkeys(session_ids))

                if not session_ids:
                    messages.error(request, "No session IDs found in CSV file")
                    return redirect(reverse("admin:posthog_team_delete_recordings", args=[object_id]))

                chunk_size = 10_000
                s3_prefix, total_chunks = store_session_id_chunks(workflow_id, session_ids, chunk_size)

                session_ids_input = RecordingsWithSessionIdsInput(
                    team_id=team.id,
                    s3_prefix=s3_prefix,
                    total_chunks=total_chunks,
                    chunk_size=chunk_size,
                    total_session_ids=len(session_ids),
                    config=config,
                    source_filename=upload_file.name or "unknown.csv",
                )

                asyncio.run(
                    temporal.start_workflow(
                        "delete-recordings-with-session-ids",
                        session_ids_input,
                        id=workflow_id,
                        task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
                        retry_policy=common.RetryPolicy(
                            maximum_attempts=2,
                            initial_interval=timedelta(minutes=1),
                        ),
                        search_attributes=team_search_attrs,
                    )
                )

                logger.info(
                    "delete_recordings_with_session_ids_triggered",
                    team_id=team.id,
                    session_ids_count=len(session_ids),
                    dry_run=dry_run,
                    reason=reason,
                    triggered_by=request.user.email,
                )

                dry_run_msg = " (DRY RUN)" if dry_run else ""
                messages.success(
                    request,
                    f"Delete recordings workflow triggered for {len(session_ids)} session ID(s){dry_run_msg}. Workflow ID: {workflow_id}",
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
            messages.error(request, "Failed to trigger workflow. Check server logs for details.")

        return redirect(reverse("admin:posthog_team_delete_recordings", args=[object_id]))

    def _get_deletion_certificate(self, team_id: int, workflow_id: str):
        """Fetch a deletion certificate from a completed Temporal workflow."""
        if not workflow_id.startswith(f"delete-recordings-{team_id}-"):
            return None, "Invalid workflow ID for this team"

        try:
            temporal = sync_connect()

            async def get_result():
                handle = temporal.get_workflow_handle(workflow_id)
                desc = await handle.describe()
                if desc.status != WorkflowExecutionStatus.COMPLETED:
                    status_name = desc.status.name.lower() if desc.status else "unknown"
                    return (
                        None,
                        f"Workflow is {status_name}, certificate is only available after completion",
                    )
                return await handle.result(), None

            certificate, error = asyncio.run(get_result())
            if error:
                return None, error
            return certificate, None
        except Exception:
            logger.exception("Failed to fetch deletion certificate", workflow_id=workflow_id)
            return None, "Internal error"

    @staticmethod
    def _format_query_for_display(query: str) -> str:
        """Format a raw query string into a human-readable filter description."""
        operator_labels = {
            "lt": "<",
            "gt": ">",
            "lte": "<=",
            "gte": ">=",
            "exact": "=",
            "is_not": "!=",
        }
        unit_suffixes = {
            "duration": "s",
        }
        parts = []
        for key, value in parse.parse_qsl(query):
            if key in ("having_predicates", "properties"):
                try:
                    filters = json.loads(value)
                    for f in filters:
                        filter_key = f.get("key", "?").replace("_", " ")
                        op = operator_labels.get(f.get("operator", ""), f.get("operator", "?"))
                        raw_value = f.get("value", "?")
                        display_value = ", ".join(raw_value) if isinstance(raw_value, list) else str(raw_value)
                        suffix = unit_suffixes.get(f.get("key", ""), "")
                        parts.append(f"{filter_key} {op} {display_value}{suffix}")
                except (json.JSONDecodeError, TypeError):
                    parts.append(f"{key}: {value}")
            else:
                label = key.replace("_", " ")
                parts.append(f"{label}: {value}")
        return ", ".join(parts) if parts else query

    def deletion_certificate_view(self, request, object_id, workflow_id):
        """Display a deletion certificate as a printable HTML page."""
        team = Team.objects.select_related("organization").get(pk=object_id)

        certificate, error = self._get_deletion_certificate(team.id, workflow_id)
        if error:
            messages.error(request, "Failed to fetch certificate. Check server logs for details.")
            return redirect(reverse("admin:posthog_team_delete_recordings", args=[object_id]))

        # workflow_id is "delete-recordings-{team_id}-{uuid}" — extract just the UUID
        reference = workflow_id.rsplit("-", 5)[-5:]
        reference_id = "-".join(reference) if len(reference) == 5 else workflow_id

        # Temporal returns timestamps as ISO strings — parse them for Django's date filter
        if isinstance(certificate, dict):
            for key in ("started_at", "completed_at"):
                if isinstance(certificate.get(key), str):
                    certificate[key] = datetime.fromisoformat(certificate[key])
        if isinstance(certificate, dict) and certificate.get("query"):
            certificate["query_display"] = self._format_query_for_display(certificate["query"])

        context = {
            **self.admin_site.each_context(request),
            "team": team,
            "certificate": certificate,
            "reference_id": reference_id,
            "title": f"Deletion Certificate - {reference_id}",
        }
        return render(request, "admin/posthog/team/deletion_certificate.html", context)

    def download_deletion_certificate_view(self, request, object_id, workflow_id):
        """Download a deletion certificate as JSON."""
        team = Team.objects.get(pk=object_id)

        certificate, error = self._get_deletion_certificate(team.id, workflow_id)
        if error:
            messages.error(request, "Failed to fetch certificate. Check server logs for details.")
            return redirect(reverse("admin:posthog_team_delete_recordings", args=[object_id]))

        response = HttpResponse(
            json.dumps(certificate, indent=2, default=str),
            content_type="application/json",
        )
        filename = f"deletion-certificate-{workflow_id}.json"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
