import json

from django.conf import settings
from django.contrib import admin
from django.forms import ModelForm, ValidationError
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from posthog.admin.console.moved import MovedToConsole
from posthog.admin.inline_registry import extra_inlines_for
from posthog.admin.inlines.events_retention_config_inline import TeamEventsRetentionConfigInline
from posthog.admin.inlines.team_marketing_analytics_config_inline import TeamMarketingAnalyticsConfigInline
from posthog.admin.organization_members import organization_members_table
from posthog.models import Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.events_retention_config import (
    OrganizationEventsRetentionConfig,
    TeamEventsRetentionConfig,
    describe_months_range,
)
from posthog.models.team.event_retention import should_enforce_events_retention
from posthog.models.team.team import DEPRECATED_ATTRS
from posthog.storage.gateway_credential_cache import validate_overspend_allowance_usd

from products.workflows.backend.facade.api import (
    get_email_sending_state,
    get_email_sending_tier_limits,
    max_email_sending_tier,
)


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
        "organization_members",
    ]

    exclude = DEPRECATED_ATTRS
    inlines = [
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
            "Organization members",
            {"fields": ["organization_members"]},
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

    @admin.display(description="Members")
    def organization_members(self, team: Team):
        if not team.pk:
            return "-"
        return organization_members_table(team.organization_id)

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
        return MovedToConsole.team_action(team, "recordings", "Delete recordings")

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
