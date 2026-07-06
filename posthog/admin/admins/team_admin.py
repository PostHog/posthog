import io
import csv
import json
import uuid
import asyncio
import hashlib
import dataclasses
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib import parse

from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import UploadedFile
from django.db import IntegrityError, transaction
from django.forms import ModelForm, ValidationError
from django.http import HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, path, reverse
from django.utils import timezone
from django.utils.html import escapejs, format_html, format_html_join
from django.utils.safestring import mark_safe

from structlog import get_logger
from temporalio import common
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import SearchAttributePair, TypedSearchAttributes

from posthog.admin.inlines.organization_member_for_related_inline import OrganizationMemberForRelatedInline
from posthog.admin.inlines.team_experiments_config_inline import TeamExperimentsConfigInline
from posthog.admin.inlines.team_marketing_analytics_config_inline import TeamMarketingAnalyticsConfigInline
from posthog.admin.inlines.user_product_list_inline import UserProductListInline
from posthog.llm.gateway_internal_client import AIGatewayInternalError, AIGatewayNotConfigured, add_credit, get_wallet
from posthog.models import Team
from posthog.models.activity_logging.activity_log import ActivityContextBase, ActivityLog, Detail, log_activity
from posthog.models.activity_logging.model_activity import is_impersonated_session
from posthog.models.group_type_mapping import invalidate_group_types_cache
from posthog.models.remote_config import RemoteConfig
from posthog.models.team.team import DEPRECATED_ATTRS
from posthog.personhog_client.client import get_personhog_client
from posthog.personhog_client.converters import proto_group_type_mapping_to_dict
from posthog.personhog_client.proto import (
    GetGroupTypeMappingsByProjectIdRequest,
    GetGroupTypeMappingsByTeamIdRequest,
    UpdateGroupTypeMappingRequest,
)
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

logger = get_logger()

# Upper bound on a single admin AI gateway top-up, to catch fat-fingered amounts.
MAX_CREDIT_USD = Decimal("1000000")


@dataclasses.dataclass(frozen=True)
class ReplayActivityContext(ActivityContextBase):
    reason: str


@dataclasses.dataclass(frozen=True)
class AIGatewayCreditActivityContext(ActivityContextBase):
    amount_usd: str
    reason: str
    balance_usd: str


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
        "delete_recordings",
        "api_token_display",
        "admit_state",
        "ai_gateway_actions",
        "ai_gateway_wallet",
        "ai_gateway_credit_history",
        "policy_cache_blob",
        "group_type_mappings_display",
    ]

    exclude = DEPRECATED_ATTRS
    inlines = [
        OrganizationMemberForRelatedInline,
        TeamMarketingAnalyticsConfigInline,
        TeamExperimentsConfigInline,
        UserProductListInline,
    ]

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
        client = get_personhog_client()
        if client is None:
            return format_html("<em>personhog client not configured</em>")
        try:
            resp = client.get_group_type_mappings_by_team_id(GetGroupTypeMappingsByTeamIdRequest(team_id=team.id))
            mappings_raw = sorted(
                [proto_group_type_mapping_to_dict(m) for m in resp.mappings],
                key=lambda d: d["group_type_index"],
            )
        except Exception as exc:
            logger.warning("admin_group_type_mappings_fetch_failed", team_id=team.id, error=str(exc))
            return format_html(
                '<p style="color: #856404; background: #fff3cd; border: 1px solid #ffc107; '
                'padding: 8px 12px; border-radius: 4px; margin: 4px 0; font-size: 13px;">'
                "Failed to fetch group type mappings from personhog</p>",
            )
        mappings = []
        for m in mappings_raw:
            detail_dashboard_id = m.get("detail_dashboard") or m.get("detail_dashboard_id")
            detail_dashboard_url = None
            if detail_dashboard_id:
                try:
                    detail_dashboard_url = reverse("admin:dashboards_dashboard_change", args=[detail_dashboard_id])
                except NoReverseMatch:
                    pass
            mappings.append(
                {
                    **m,
                    "detail_dashboard_id": detail_dashboard_id,
                    "detail_dashboard_url": detail_dashboard_url,
                    "edit_url": reverse(
                        "admin:posthog_team_edit_group_type_mapping",
                        args=[team.pk, m["group_type_index"]],
                    ),
                }
            )
        # nosemgrep: python.django.security.audit.avoid-mark-safe.avoid-mark-safe (admin-only, renders trusted template)
        return mark_safe(
            render_to_string(
                "admin/posthog/team/group_type_mappings_display.html",
                {"mappings": mappings, "team": team},
                request=getattr(self, "_current_request", None),
            )
        )

    def _get_personhog_client_or_error(self, request, redirect_url):
        """Return (client, None) or (None, redirect_response) if personhog is unavailable."""
        client = get_personhog_client()
        if client is None:
            messages.error(request, "personhog client is not configured — cannot manage group type mappings.")
            return None, redirect(redirect_url)
        return client, None

    def _fetch_group_type_mapping_via_personhog(self, client, project_id, group_type_index):
        """Fetch a single mapping from personhog by project_id + group_type_index. Returns dict or None."""
        resp = client.get_group_type_mappings_by_project_id(
            GetGroupTypeMappingsByProjectIdRequest(project_id=project_id)
        )
        for m in resp.mappings:
            d = proto_group_type_mapping_to_dict(m)
            if d["group_type_index"] == group_type_index:
                return d
        return None

    def edit_group_type_mapping_view(self, request, object_id, group_type_index):
        team = Team.objects.select_related("project").get(pk=object_id)
        if not self.has_change_permission(request, team):
            raise PermissionDenied
        group_type_index = int(group_type_index)
        team_url = reverse("admin:posthog_team_change", args=[object_id])

        client, err_response = self._get_personhog_client_or_error(request, team_url)
        if err_response is not None:
            return err_response

        try:
            mapping_dict = self._fetch_group_type_mapping_via_personhog(client, team.project_id, group_type_index)
        except Exception as exc:
            logger.warning(
                "admin_group_type_mapping_fetch_failed",
                team_id=team.id,
                group_type_index=group_type_index,
                error=str(exc),
            )
            messages.warning(request, "Failed to fetch group type mappings from personhog")
            return redirect(team_url)

        if mapping_dict is None:
            messages.error(request, f"Group type mapping with index {group_type_index} not found for this team.")
            return redirect(team_url)

        if request.method == "GET":
            default_columns = mapping_dict.get("default_columns")
            default_columns_json = json.dumps(default_columns) if default_columns else ""
            context = {
                **self.admin_site.each_context(request),
                "team": team,
                "mapping": mapping_dict,
                "default_columns_json": default_columns_json,
                "title": f"Edit group type mapping - {team.name} - index {group_type_index}",
            }
            return render(request, "admin/posthog/team/group_type_mapping_edit.html", context)
        if request.method != "POST":
            return HttpResponseNotAllowed(["GET", "POST"])

        name_singular = request.POST.get("name_singular", "").strip()
        name_plural = request.POST.get("name_plural", "").strip()

        default_columns_raw = request.POST.get("default_columns", "").strip()
        parsed_default_columns: list[str] | None = None
        if default_columns_raw:
            try:
                parsed = json.loads(default_columns_raw)
                if not isinstance(parsed, list):
                    raise ValueError
                parsed_default_columns = parsed
            except (json.JSONDecodeError, ValueError):
                messages.error(request, "Default columns must be a valid JSON array.")
                return redirect(
                    reverse("admin:posthog_team_edit_group_type_mapping", args=[object_id, group_type_index])
                )

        update_mask = ["name_singular", "name_plural"]
        update_kwargs: dict[str, Any] = {
            "project_id": team.project_id,
            "group_type_index": group_type_index,
            "name_singular": name_singular,
            "name_plural": name_plural,
        }
        if default_columns_raw:
            update_mask.append("default_columns")
            if parsed_default_columns is not None:
                update_kwargs["default_columns"] = json.dumps(parsed_default_columns).encode()
        update_kwargs["update_mask"] = update_mask

        try:
            client.update_group_type_mapping(UpdateGroupTypeMappingRequest(**update_kwargs))
        except Exception as exc:
            logger.exception(
                "admin_edit_group_type_mapping_failed",
                team_id=team.id,
                group_type_index=group_type_index,
                error=str(exc),
            )
            messages.error(request, f"Failed to update via personhog: {exc}")
            return redirect(reverse("admin:posthog_team_edit_group_type_mapping", args=[object_id, group_type_index]))

        if team.project_id:
            invalidate_group_types_cache(team.project_id)

        logger.info(
            "admin_edit_group_type_mapping",
            team_id=team.id,
            group_type_index=group_type_index,
            fields=update_kwargs["update_mask"],
            triggered_by=request.user.email,
        )
        messages.success(
            request,
            f"Updated group type mapping (index {group_type_index}) for team '{team.name}'.",
        )
        return redirect(reverse("admin:posthog_team_change", args=[object_id]))

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

    @admin.display(description="API token")
    def api_token_display(self, team: Team):
        if not team.pk:
            return "-"
        set_url = reverse("admin:posthog_team_set_api_token", args=[team.pk])
        return format_html(
            '<span>{}</span> &nbsp; <a class="button" href="{}">Set API token</a>',
            team.api_token,
            set_url,
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

    def _resolve_ai_gateway_team(self, request, object_id):
        if request.method != "POST":
            return None, HttpResponseNotAllowed(["POST"])
        team = Team.objects.get(pk=object_id)
        if not self.has_change_permission(request, team):
            raise PermissionDenied
        return team, None

    def _refresh_ai_gateway_policy_cache(self, team: Team) -> None:
        # Sync write: the post_save signal's Celery task races the redirect,
        # and idempotent clicks skip team.save() so the signal never fires.
        from posthog.storage.team_llm_gateway_policy_cache import update_team_llm_gateway_policy_cache

        update_team_llm_gateway_policy_cache(team)

    def enable_ai_gateway_view(self, request, object_id):
        team, response = self._resolve_ai_gateway_team(request, object_id)
        if response is not None:
            return response
        if team.llm_gateway_enabled_at is None:
            team.llm_gateway_enabled_at = timezone.now()
            team.save()
            logger.info(
                "admin_enable_ai_gateway",
                team_id=team.id,
                triggered_by=request.user.email,
            )
            self.message_user(
                request,
                f"Enabled AI gateway access for team '{team.name}'.",
                level=messages.SUCCESS,
            )
        else:
            self.message_user(
                request,
                f"Team '{team.name}' was already enabled (since {team.llm_gateway_enabled_at.isoformat()}).",
                level=messages.INFO,
            )
        self._refresh_ai_gateway_policy_cache(team)
        return redirect(reverse("admin:posthog_team_change", args=[object_id]))

    def revoke_ai_gateway_view(self, request, object_id):
        team, response = self._resolve_ai_gateway_team(request, object_id)
        if response is not None:
            return response
        if team.llm_gateway_revoked_at is None:
            team.llm_gateway_revoked_at = timezone.now()
            team.save()
            logger.info(
                "admin_revoke_ai_gateway",
                team_id=team.id,
                triggered_by=request.user.email,
            )
            self.message_user(
                request,
                f"Revoked AI gateway access for team '{team.name}'.",
                level=messages.WARNING,
            )
        else:
            self.message_user(
                request,
                f"Team '{team.name}' was already revoked (since {team.llm_gateway_revoked_at.isoformat()}).",
                level=messages.INFO,
            )
        self._refresh_ai_gateway_policy_cache(team)
        return redirect(reverse("admin:posthog_team_change", args=[object_id]))

    def clear_ai_gateway_revoke_view(self, request, object_id):
        team, response = self._resolve_ai_gateway_team(request, object_id)
        if response is not None:
            return response
        if team.llm_gateway_revoked_at is not None:
            team.llm_gateway_revoked_at = None
            team.save()
            logger.info(
                "admin_clear_ai_gateway_revoke",
                team_id=team.id,
                triggered_by=request.user.email,
            )
            self.message_user(
                request,
                f"Cleared AI gateway revoke for team '{team.name}'.",
                level=messages.SUCCESS,
            )
        else:
            self.message_user(
                request,
                f"Team '{team.name}' was not revoked.",
                level=messages.INFO,
            )
        self._refresh_ai_gateway_policy_cache(team)
        return redirect(reverse("admin:posthog_team_change", args=[object_id]))

    def add_ai_gateway_credit_view(self, request, object_id):
        team = Team.objects.get(pk=object_id)
        if not self.has_change_permission(request, team):
            raise PermissionDenied

        credit_url = reverse("admin:posthog_team_add_ai_gateway_credit", args=[object_id])

        if request.method == "GET":
            context = {
                **self.admin_site.each_context(request),
                "team": team,
                "title": f"Add AI gateway credit - {team.name}",
                # Per-render nonce; combined with amount + reason on submit to form the
                # idempotency key, so a double-submit dedupes but a back-edit-resubmit
                # of a different amount is treated as a new top-up.
                "form_nonce": str(uuid.uuid4()),
            }
            return render(request, "admin/posthog/team/add_ai_gateway_credit_form.html", context)

        amount_raw = request.POST.get("amount_usd", "").strip()
        reason = request.POST.get("reason", "").strip()
        form_nonce = request.POST.get("form_nonce", "").strip() or str(uuid.uuid4())

        if not reason:
            messages.error(request, "Reason is required")
            return redirect(credit_url)
        try:
            amount = Decimal(amount_raw)
        except InvalidOperation:
            messages.error(request, "Amount must be a valid decimal")
            return redirect(credit_url)
        # is_finite() rejects NaN/sNaN/±Inf before `amount <= 0`, which raises on NaN.
        if not amount.is_finite() or amount <= 0:
            messages.error(request, "Amount must be a positive number")
            return redirect(credit_url)
        if amount > MAX_CREDIT_USD:
            messages.error(request, f"Amount exceeds the ${MAX_CREDIT_USD:,} per-top-up limit")
            return redirect(credit_url)

        # Bind the key to the amount + reason so editing the amount after a submit
        # produces a new key instead of replaying the prior top-up.
        idempotency_key = hashlib.sha256(f"{form_nonce}:{amount}:{reason}".encode()).hexdigest()
        try:
            result = add_credit(team.id, str(amount), reason, idempotency_key)
        except AIGatewayInternalError as exc:
            logger.warning(
                "admin_add_ai_gateway_credit_failed",
                team_id=team.id,
                amount_usd=amount_raw,
                error=str(exc),
                triggered_by=request.user.email,
            )
            messages.error(request, f"Failed to add credit: {exc}")
            return redirect(credit_url)

        logger.info(
            "admin_add_ai_gateway_credit",
            team_id=team.id,
            amount_usd=str(amount),
            entry_id=result.entry_id,
            duplicate=result.duplicate,
            triggered_by=request.user.email,
        )
        # Audit is keyed by the ledger entry_id, so write it whenever one is missing.
        # The credit (gateway) and this record (Postgres) can't share a transaction,
        # so a replay backfills the audit if an earlier attempt's write was lost after
        # the money moved. The existence check dedupes best-effort; admin-only, so a
        # concurrent-double-submit race writing a second row isn't worth a constraint.
        if not ActivityLog.objects.filter(scope="AIGatewayCredit", item_id=result.entry_id).exists():
            log_activity(
                organization_id=team.organization_id,
                team_id=team.id,
                user=request.user,
                was_impersonated=is_impersonated_session(request),
                item_id=result.entry_id,
                scope="AIGatewayCredit",
                activity="credit_added",
                detail=Detail(
                    name=f"AI gateway credit — ${result.amount_usd}",
                    type="admin_add_credit",
                    context=AIGatewayCreditActivityContext(
                        amount_usd=result.amount_usd,
                        reason=reason,
                        balance_usd=result.balance_usd,
                    ),
                ),
            )
        if result.duplicate:
            messages.info(
                request,
                f"Idempotent replay — no new credit. Team '{team.name}' balance: ${result.balance_usd}.",
            )
        else:
            messages.success(
                request,
                f"Added ${result.amount_usd} to team '{team.name}'. New balance: ${result.balance_usd}.",
            )
        return redirect(reverse("admin:posthog_team_change", args=[object_id]))

    @admin.display(description="Actions")
    def ai_gateway_actions(self, team: Team):
        if not team.pk:
            return "-"
        # nosemgrep: python.django.security.audit.avoid-mark-safe.avoid-mark-safe (admin-only, renders trusted template)
        return mark_safe(
            render_to_string(
                "admin/posthog/team/ai_gateway_actions.html",
                {
                    "team": team,
                    "enable_url": reverse("admin:posthog_team_enable_ai_gateway", args=[team.pk]),
                    "revoke_url": reverse("admin:posthog_team_revoke_ai_gateway", args=[team.pk]),
                    "clear_revoke_url": reverse("admin:posthog_team_clear_ai_gateway_revoke", args=[team.pk]),
                    "team_name_escaped": escapejs(team.name),
                    "is_enabled": team.llm_gateway_enabled_at is not None,
                    "is_revoked": team.llm_gateway_revoked_at is not None,
                },
            )
        )

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
        return format_html("<em>Not enrolled</em>")

    @admin.display(description="Wallet (AI gateway credits)")
    def ai_gateway_wallet(self, team: Team):
        if not team.pk:
            return "-"
        # The balance read is a blocking call to the gateway, so defer it behind a
        # link (mirrors remote_config_cache_actions) instead of fetching on every
        # team page render.
        # nosemgrep: python.django.security.audit.avoid-mark-safe.avoid-mark-safe (admin-only, renders trusted template)
        return mark_safe(
            render_to_string(
                "admin/posthog/team/ai_gateway_wallet_actions.html",
                {
                    "wallet_url": reverse("admin:posthog_team_ai_gateway_wallet", args=[team.pk]),
                    "add_credit_url": reverse("admin:posthog_team_add_ai_gateway_credit", args=[team.pk]),
                },
            )
        )

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
            return format_html("<em>(no top-ups recorded)</em>")
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

    def ai_gateway_wallet_view(self, request, object_id):
        team = Team.objects.get(pk=object_id)
        if not self.has_view_permission(request, team):
            raise PermissionDenied
        context = {
            **self.admin_site.each_context(request),
            "team": team,
            "title": f"AI gateway wallet - {team.name}",
            "add_credit_url": reverse("admin:posthog_team_add_ai_gateway_credit", args=[team.pk]),
        }
        try:
            context["wallet"] = get_wallet(team.id)
        except AIGatewayNotConfigured:
            context["error"] = "ai-gateway internal API not configured in this region"
        except AIGatewayInternalError as exc:
            context["error"] = f"wallet unavailable: {exc}"
        return render(request, "admin/posthog/team/ai_gateway_wallet_page.html", context)

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
            return format_html("<em>(no entry in Redis for this team; gateway denies until something writes one)</em>")
        if source == "redis_negative":
            return format_html(
                "<em>(negative-cache sentinel in Redis; gateway treats as default-deny "
                "until the entry expires, default 24h)</em>"
            )
        return format_html("<pre>{}</pre>", json.dumps(blob, indent=2, default=str))

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/group-type-mapping/<int:group_type_index>/edit/",
                self.admin_site.admin_view(self.edit_group_type_mapping_view),
                name="posthog_team_edit_group_type_mapping",
            ),
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
                "<path:object_id>/set-api-token/",
                self.admin_site.admin_view(self.set_api_token_view),
                name="posthog_team_set_api_token",
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
            path(
                "<path:object_id>/delete-recordings/workflows/",
                self.admin_site.admin_view(self.delete_recordings_workflows_fragment),
                name="posthog_team_delete_recordings_workflows",
            ),
            path(
                "<path:object_id>/enable-ai-gateway/",
                self.admin_site.admin_view(self.enable_ai_gateway_view),
                name="posthog_team_enable_ai_gateway",
            ),
            path(
                "<path:object_id>/revoke-ai-gateway/",
                self.admin_site.admin_view(self.revoke_ai_gateway_view),
                name="posthog_team_revoke_ai_gateway",
            ),
            path(
                "<path:object_id>/clear-ai-gateway-revoke/",
                self.admin_site.admin_view(self.clear_ai_gateway_revoke_view),
                name="posthog_team_clear_ai_gateway_revoke",
            ),
            path(
                "<path:object_id>/add-ai-gateway-credit/",
                self.admin_site.admin_view(self.add_ai_gateway_credit_view),
                name="posthog_team_add_ai_gateway_credit",
            ),
            path(
                "<path:object_id>/ai-gateway-wallet/",
                self.admin_site.admin_view(self.ai_gateway_wallet_view),
                name="posthog_team_ai_gateway_wallet",
            ),
        ]
        return custom_urls + urls

    def set_api_token_view(self, request, object_id):
        team = Team.objects.get(pk=object_id)
        if not self.has_change_permission(request, team):
            raise PermissionDenied

        if request.method == "GET":
            context = {
                **self.admin_site.each_context(request),
                "team": team,
                "title": f"Set API token - {team.name}",
            }
            return render(request, "admin/posthog/team/set_api_token_form.html", context)

        new_token = request.POST.get("new_token", "").strip()
        if not new_token:
            messages.error(request, "New API token is required")
            return redirect(reverse("admin:posthog_team_set_api_token", args=[object_id]))

        try:
            with transaction.atomic():
                team.set_token_and_save(
                    new_token=new_token,
                    user=request.user,
                    is_impersonated_session=False,
                )
        except ValueError as e:
            messages.error(request, str(e))
            return redirect(reverse("admin:posthog_team_set_api_token", args=[object_id]))
        except IntegrityError:
            messages.error(request, "Another team already owns this API token. Pick a different value.")
            return redirect(reverse("admin:posthog_team_set_api_token", args=[object_id]))

        logger.info(
            "admin_set_api_token",
            team_id=team.id,
            triggered_by=request.user.email,
        )
        messages.success(request, f"API token updated for team '{team.name}'.")
        return redirect(reverse("admin:posthog_team_change", args=[object_id]))

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
