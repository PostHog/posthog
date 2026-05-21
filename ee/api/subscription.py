import uuid
import asyncio
from typing import Any, Optional

from django.conf import settings
from django.core.cache import cache
from django.db.models import QuerySet
from django.http import HttpRequest, JsonResponse

import jwt
import posthoganalytics
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_field,
    extend_schema_view,
)
from rest_framework import exceptions, filters, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.cloud_utils import is_cloud
from posthog.constants import (
    SUBSCRIPTION_AI_PROMPT_FEATURE_FLAG_KEY,
    SUBSCRIPTION_AI_SUMMARY_PROMPT_GUIDE_FEATURE_FLAG_KEY,
    AvailableFeature,
)
from posthog.event_usage import groups
from posthog.exceptions import QuotaLimitExceeded
from posthog.exceptions_capture import capture_exception
from posthog.models import Insight
from posthog.models.integration import Integration
from posthog.models.subscription import Subscription, SubscriptionDelivery, unsubscribe_using_token
from posthog.permissions import PremiumFeaturePermission
from posthog.rate_limit import SubscriptionTestDeliveryThrottle
from posthog.resource_limits import LimitKey, check_count_limit, get_organization_limit
from posthog.security.url_validation import is_url_allowed
from posthog.slo.context import SloSpec, slo_operation
from posthog.slo.types import SloArea, SloOperation
from posthog.temporal.common.client import sync_connect
from posthog.temporal.subscriptions.types import ProcessSubscriptionWorkflowInputs, SubscriptionTriggerType
from posthog.utils import str_to_bool

from ee.hogai.ai_reports import AiReportStageError, generate_ai_report
from ee.tasks.subscriptions.ai_subscription.spec_generator import (
    ALLOWED_AI_MODELS,
    PROMPT_MAX_LENGTH as AI_PROMPT_MAX_LENGTH,
    PromptRejectedError,
    sanitize_prompt,
)
from ee.tasks.subscriptions.auto_disable import validate_re_enable
from ee.tasks.subscriptions.subscription_utils import DEFAULT_MAX_ASSET_COUNT

SUMMARY_QUOTA_CACHE_TTL_SECONDS = 60
SUMMARY_CAP_HIT_DEDUPE_TTL_SECONDS = 600


def _summary_quota_cache_key(organization_id) -> str:
    return f"subscription:summary_quota:org:{organization_id}"


def _summary_cap_hit_dedupe_key(organization_id) -> str:
    return f"subscription:summary_cap_hit:org:{organization_id}"


def _count_active_summaries(organization) -> int:
    """Count subscriptions with summary_enabled=True (and not soft-deleted) across
    every team in this organization. Single source of truth for both the cap-check
    in the serializer and the `summary_quota` action endpoint."""
    return Subscription.objects.filter(
        team__organization_id=organization.id,
        summary_enabled=True,
        deleted=False,
    ).count()


def _invalidate_summary_quota_cache(organization_id) -> None:
    cache.delete(_summary_quota_cache_key(organization_id))


_AI_CONFIG_ALLOWED_KEYS = frozenset({"model", "planner_model"})


def _validate_ai_config_dict(value):
    """Reject unknown keys + non-whitelisted models at the API boundary so the only
    values we ever persist are the ones `resolve_ai_model` actually consumes —
    otherwise an attacker can stash arbitrary JSON that activates later if the
    delivery-time allowlist grows. Shared between `AiReportRequestSerializer` and
    `SubscriptionSerializer` so the two field validators don't drift."""
    if value is None:
        return value
    if not isinstance(value, dict):
        raise ValidationError("ai_config must be an object.")
    unknown = set(value.keys()) - _AI_CONFIG_ALLOWED_KEYS
    if unknown:
        raise ValidationError(
            f"ai_config keys must be a subset of {sorted(_AI_CONFIG_ALLOWED_KEYS)}; got unknown {sorted(unknown)}."
        )
    for key in _AI_CONFIG_ALLOWED_KEYS & value.keys():
        model_val = value[key]
        if not isinstance(model_val, str) or model_val not in ALLOWED_AI_MODELS:
            raise ValidationError(f"ai_config.{key} must be one of {sorted(ALLOWED_AI_MODELS)}; got {model_val!r}.")
    return value


def _ai_create_gate_reason(organization, *, kind: str = "subscriptions", verb: str = "creating") -> Optional[str]:
    """Returns the human-readable reason why creating an AI subscription / ad-hoc AI
    report should be rejected, or `None` if all gates pass. Shared between
    `SubscriptionSerializer`'s create-time validation and the ad-hoc `ai_report`
    endpoint so the gate set stays in sync as new gates are added. Callers
    translate the returned reason into the response shape appropriate for their
    context (ValidationError vs. 403 Response).

    `kind` and `verb` swap the noun in the messages so the caller controls user-facing
    wording ("AI subscriptions" vs "AI reports", "creating" vs "generating").
    """
    if not settings.DEBUG and not is_cloud():
        return f"AI {kind} are only available in PostHog Cloud."
    if not organization.is_ai_data_processing_approved:
        return f"Your organization must approve AI data processing before {verb} AI {kind}."
    # DEBUG-mode dev environments skip the network feature-flag check so local
    # testing doesn't require provisioning a flag in the analytics backend.
    if not settings.DEBUG and not posthoganalytics.feature_enabled(
        SUBSCRIPTION_AI_PROMPT_FEATURE_FLAG_KEY,
        str(organization.id),
        groups={"organization": str(organization.id)},
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    ):
        return f"AI {kind} are not enabled for your organization."
    return None


class AiReportRequestSerializer(serializers.Serializer):
    """Input for the ad-hoc AI report endpoint — same prompt validation as a scheduled AI subscription."""

    prompt = serializers.CharField(
        required=True,
        max_length=AI_PROMPT_MAX_LENGTH,
        help_text=f"Natural-language prompt describing the report. Max {AI_PROMPT_MAX_LENGTH} characters.",
    )
    window_days = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=365,
        default=7,
        help_text="Analysis window in days the planner should consider. Defaults to 7 (last week).",
    )
    ai_config = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text=(
            "Optional configuration; supports keys `model` (synthesis model) and `planner_model`. "
            "Values outside the allowed model whitelist are rejected."
        ),
    )

    def validate_ai_config(self, value):
        return _validate_ai_config_dict(value)


class AiReportResponseSerializer(serializers.Serializer):
    """Output for the ad-hoc AI report endpoint."""

    markdown = serializers.CharField(help_text="The LLM-synthesized report, rendered as commonmark markdown.")


@extend_schema_field({"type": "array", "items": {"type": "integer"}})
class DashboardExportInsightsField(serializers.Field):
    """Custom field to handle ManyToMany dashboard_export_insights as a list of IDs."""

    def to_representation(self, value):
        return [obj.id for obj in value.all()]

    def to_internal_value(self, data):
        if not isinstance(data, list):
            raise serializers.ValidationError("Expected a list of insight IDs.")
        for item in data:
            if not isinstance(item, int):
                raise serializers.ValidationError("All items must be integers.")
        return data


class SubscriptionSerializer(serializers.ModelSerializer):
    """Standard Subscription serializer."""

    created_by = UserBasicSerializer(read_only=True)
    summary = serializers.CharField(read_only=True, help_text="Human-readable schedule summary, e.g. 'sent daily'.")
    invite_message = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Optional message included in the invitation email when adding new recipients.",
    )
    integration_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="ID of a connected Slack integration. Required when target_type is slack.",
    )
    dashboard_export_insights = DashboardExportInsightsField(
        required=False,
        help_text="List of insight IDs from the dashboard to include. Required for dashboard subscriptions, max 6.",
    )
    insight_short_id = serializers.SerializerMethodField()
    resource_name = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = [
            "id",
            "content_type",
            "dashboard",
            "insight",
            "insight_short_id",
            "resource_name",
            "dashboard_export_insights",
            "prompt",
            "ai_config",
            "target_type",
            "target_value",
            "frequency",
            "interval",
            "byweekday",
            "bysetpos",
            "count",
            "start_date",
            "until_date",
            "created_at",
            "created_by",
            "deleted",
            "enabled",
            "title",
            "summary",
            "next_delivery_date",
            "integration_id",
            "invite_message",
            "summary_enabled",
            "summary_prompt_guide",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "created_by",
            "next_delivery_date",
            "summary",
            "insight_short_id",
            "resource_name",
        ]
        extra_kwargs = {
            "content_type": {
                "help_text": (
                    "What the subscription delivers: 'insight' (snapshot of one insight), "
                    "'dashboard' (snapshot of one dashboard), or 'ai_prompt' (LLM-generated report). "
                    "Cannot be changed after creation."
                ),
            },
            "prompt": {
                "help_text": (
                    "Free-text prompt that drives the AI-generated report. Required when "
                    "content_type is 'ai_prompt'. Max 4000 characters."
                ),
            },
            "ai_config": {
                "help_text": (
                    "Optional AI subscription configuration. Currently supports the keys "
                    "'model' (synthesis model) and 'planner_model'. Unknown keys and values "
                    "outside the allowed model whitelist are rejected with a 400 at the API boundary."
                ),
            },
            "dashboard": {"help_text": "Dashboard ID to subscribe to (mutually exclusive with insight on create)."},
            "insight": {"help_text": "Insight ID to subscribe to (mutually exclusive with dashboard on create)."},
            "target_type": {"help_text": "Delivery channel: email, slack, or webhook."},
            "target_value": {
                "help_text": "Recipient(s): comma-separated email addresses for email, Slack channel name/ID for slack, or full URL for webhook."
            },
            "frequency": {"help_text": "How often to deliver: daily, weekly, monthly, or yearly."},
            "interval": {
                "help_text": "Interval multiplier (e.g. 2 with weekly frequency means every 2 weeks). Default 1."
            },
            "byweekday": {
                "help_text": "Days of week for weekly subscriptions: monday, tuesday, wednesday, thursday, friday, saturday, sunday."
            },
            "bysetpos": {
                "help_text": "Position within byweekday set for monthly frequency (e.g. 1 for first, -1 for last)."
            },
            "count": {"help_text": "Total number of deliveries before the subscription stops. Null for unlimited."},
            "start_date": {"help_text": "When to start delivering (ISO 8601 datetime)."},
            "until_date": {"help_text": "When to stop delivering (ISO 8601 datetime). Null for indefinite."},
            "title": {"help_text": "Human-readable name for this subscription."},
            "deleted": {"help_text": "Set to true to soft-delete. Subscriptions cannot be hard-deleted."},
            "enabled": {
                "help_text": "Whether the subscription is active. Set to false to pause delivery without deleting. Auto-set to false when the delivery integration becomes invalid."
            },
        }

    def get_insight_short_id(self, obj: Subscription) -> Optional[str]:
        if obj.insight_id and obj.insight is not None:
            return obj.insight.short_id
        return None

    def get_resource_name(self, obj: Subscription) -> Optional[str]:
        info = obj.resource_info
        return info.name if info else None

    def validate_ai_config(self, value):
        return _validate_ai_config_dict(value)

    def validate(self, attrs):
        existing = self.instance

        if attrs.get("dashboard") and attrs["dashboard"].team.id != self.context["team_id"]:
            raise ValidationError({"dashboard": ["This dashboard does not belong to your team."]})

        if attrs.get("insight") and attrs["insight"].team.id != self.context["team_id"]:
            raise ValidationError({"insight": ["This insight does not belong to your team."]})

        # `content_type` is set at create time and pinned afterwards — switching kind
        # mid-life would leave stale fields populated for the previous kind
        # (`insight_id` on an AI sub, `prompt` on an insight sub) and the delivery
        # path can't reason about that. Surfaces the help_text contract as code.
        if existing is not None and "content_type" in attrs and attrs["content_type"] != existing.content_type:
            raise ValidationError(
                {"content_type": ["content_type cannot be changed after the subscription is created."]}
            )

        has_insight = attrs.get("insight") or (existing and existing.insight_id)
        has_dashboard = attrs.get("dashboard") or (existing and existing.dashboard_id)
        # Use explicit-key check so a deliberate `""` in the PATCH body doesn't fall
        # through to the stale instance value and pass validation while writing empty
        # to the DB (the next delivery would then PromptRejectedError + auto-disable).
        prompt_value = attrs["prompt"] if "prompt" in attrs else (existing.prompt if existing else None)
        has_prompt = (prompt_value or "").strip()

        # `content_type` was added late; legacy callers (and the dashboard-subscription
        # tests they shipped against) omit it and rely on `dashboard`/`insight` to imply
        # the kind. Honour an explicit value if present, otherwise infer from the
        # populated FK so existing paths keep their original validation errors. Persist
        # the inferred value to `attrs` so the create path stores the right discriminator
        # (the model default is INSIGHT, which would mis-classify dashboard subs).
        explicit_content_type = attrs.get("content_type") or (existing.content_type if existing else None)
        if explicit_content_type:
            content_type = explicit_content_type
        elif has_dashboard:
            content_type = Subscription.ContentType.DASHBOARD
        else:
            content_type = Subscription.ContentType.INSIGHT
        if existing is None and "content_type" not in attrs:
            attrs["content_type"] = content_type

        if content_type == Subscription.ContentType.INSIGHT:
            if not has_insight:
                raise ValidationError({"insight": ["Insight is required for insight subscriptions."]})
            if attrs.get("dashboard") or attrs.get("prompt"):
                raise ValidationError({"insight": ["Insight subscriptions cannot also set dashboard or prompt."]})
            if attrs.get("ai_config") is not None:
                raise ValidationError({"ai_config": ["ai_config is only valid on AI subscriptions."]})
        elif content_type == Subscription.ContentType.DASHBOARD:
            if not has_dashboard:
                raise ValidationError({"dashboard": ["Dashboard is required for dashboard subscriptions."]})
            if attrs.get("insight") or attrs.get("prompt"):
                raise ValidationError("Dashboard subscriptions cannot also set insight or prompt.")
            if attrs.get("ai_config") is not None:
                raise ValidationError({"ai_config": ["ai_config is only valid on AI subscriptions."]})
        elif content_type == Subscription.ContentType.AI_PROMPT:
            if attrs.get("insight") or attrs.get("dashboard"):
                raise ValidationError("AI subscriptions cannot also set insight or dashboard.")
            if not has_prompt:
                raise ValidationError({"prompt": ["Prompt is required for AI subscriptions."]})
            if len(has_prompt) > AI_PROMPT_MAX_LENGTH:
                raise ValidationError({"prompt": [f"Prompt cannot exceed {AI_PROMPT_MAX_LENGTH} characters."]})
            # The delivery activity rejects unsupported targets, but auto-disabling
            # on the first scheduled run is a poor first impression — fail fast here.
            effective_target_type = attrs.get("target_type") or (existing.target_type if existing else None)
            if effective_target_type and effective_target_type not in (
                Subscription.SubscriptionTarget.EMAIL,
                Subscription.SubscriptionTarget.SLACK,
            ):
                raise ValidationError({"target_type": ["AI subscriptions only support email or slack delivery."]})

            # Cloud / consent / feature-flag gates fire on create only. `content_type` is
            # pinned (rejected earlier in this method), so an existing AI subscription
            # cannot be created by mutation. Existing AI subs remain editable after
            # consent revoke or flag-off — owners can still disable/delete them, and
            # the delivery path is the authoritative cost gate.
            if existing is None:
                gate_reason = _ai_create_gate_reason(self.context["get_organization"]())
                if gate_reason is not None:
                    raise ValidationError(gate_reason)

        self._validate_dashboard_export_subscription(attrs)

        target_type = attrs.get("target_type") or (self.instance.target_type if self.instance else None)
        # Use explicit-key check for integration_id so a deliberate `null` in the PATCH
        # body falls through to the validation below — `or` would silently coalesce
        # to the stale instance value and pass `validate_re_enable` with the wrong id.
        integration_id = (
            attrs["integration_id"]
            if "integration_id" in attrs
            else (self.instance.integration_id if self.instance else None)
        )

        # Reject re-enables of subscriptions whose delivery prerequisite is still
        # permanently broken — otherwise the next delivery would just auto-disable
        # them again.
        is_re_enabling = self.instance is not None and attrs.get("enabled") is True and self.instance.enabled is False
        if is_re_enabling:
            error_message = validate_re_enable(target_type, integration_id)
            if error_message:
                raise ValidationError({"enabled": [error_message]})
            # AI subs auto-disable on PromptRejectedError (deleted creator, prompt now
            # fails sanitization). The delivery path will just re-disable on the next
            # tick unless the underlying cause is fixed by this PATCH.
            if content_type == Subscription.ContentType.AI_PROMPT:
                prompt_after = attrs.get("prompt") if "prompt" in attrs else (existing.prompt if existing else None)
                created_by_after = existing.created_by if existing else None
                if created_by_after is None:
                    raise ValidationError(
                        {"enabled": ["Cannot re-enable AI subscription: the original creator is unavailable."]}
                    )
                try:
                    sanitize_prompt(prompt_after)
                except PromptRejectedError as exc:
                    # Surface under "enabled" not "prompt" — the user's PATCH likely
                    # only flipped `enabled=true` and didn't touch `prompt`. Pointing
                    # the error at the field they actually changed makes the cause
                    # diagnosable. The reason still names the prompt.
                    raise ValidationError(
                        {"enabled": [f"Cannot re-enable AI subscription: prompt is invalid ({exc})."]}
                    )

        # Reject mutations that would land `next_delivery_date=None` — `enabled=True`
        # with a null next_delivery_date is invisible to the scheduler (the
        # `__lte=now` filter in `fetch_due_subscriptions_activity` drops nulls).
        # Three reachable paths: re-enable an exhausted sub, create one with a bad
        # rrule, or PATCH an active sub's schedule into exhaustion.
        check_schedule = (
            is_re_enabling
            or self.instance is None
            or (self.instance is not None and self.instance.enabled and bool(Subscription.RRULE_FIELDS & attrs.keys()))
        )
        if check_schedule and Subscription.project_next_delivery_date(instance=self.instance, **attrs) is None:
            base = "Subscription schedule has reached its end date. Extend until_date or remove count"
            if is_re_enabling:
                raise ValidationError({"enabled": [f"{base} before re-enabling."]})
            if self.instance is None:
                raise ValidationError({"start_date": [f"{base}."]})
            raise ValidationError(f"{base}.")

        if target_type == Subscription.SubscriptionTarget.SLACK:
            if not integration_id:
                raise ValidationError({"integration_id": ["A Slack integration is required for Slack subscriptions."]})
            try:
                integration = Integration.objects.get(id=integration_id, team_id=self.context["team_id"])
            except Integration.DoesNotExist:
                raise ValidationError(
                    {"integration_id": ["This integration does not exist or does not belong to your team."]}
                )
            if integration.kind != "slack":
                raise ValidationError({"integration_id": ["Slack subscriptions require a Slack integration."]})

        # SSRF protection for webhook subscriptions
        target_value = attrs.get("target_value") or (self.instance.target_value if self.instance else None)
        if target_type == Subscription.SubscriptionTarget.WEBHOOK and target_value:
            allowed, error = is_url_allowed(target_value)
            if not allowed:
                raise ValidationError({"target_value": [f"Invalid webhook URL: {error}"]})

        # Only gate non-empty writes to `summary_prompt_guide`. Clearing (empty string)
        # and field-absent PATCHes always pass through so users aren't stuck with a value
        # they can no longer edit if the flag flips off after they set one.
        prompt_guide = attrs.get("summary_prompt_guide")
        if prompt_guide:
            if len(prompt_guide) > 500:
                raise ValidationError({"summary_prompt_guide": ["AI summary context must be 500 characters or fewer."]})
            if not self._prompt_guide_feature_enabled():
                raise exceptions.PermissionDenied("Setting AI summary context is not enabled for this organization.")

        if attrs.get("summary_enabled"):
            organization = self.context["get_organization"]()
            if not organization.is_ai_data_processing_approved:
                raise exceptions.PermissionDenied(
                    "AI data processing must be approved by your organization before enabling AI summaries"
                )

        # Cap gate: fire whenever the row is *becoming* an active summary
        # (summary_enabled=True AND deleted=False) but wasn't before. This
        # catches creates with the toggle on, off→on transitions, AND
        # restoring a soft-deleted summary that was already summary_enabled
        # — otherwise PATCHing `deleted=False` on a grandfathered row would
        # bypass the cap entirely.
        if self._is_becoming_active_summary(attrs):
            organization = self.context["get_organization"]()
            self._validate_summary_enabled_org_limit(organization)

        return attrs

    def _is_becoming_active_summary(self, attrs: dict) -> bool:
        pre_summary_enabled = self.instance.summary_enabled if self.instance else False
        pre_deleted = self.instance.deleted if self.instance else False
        post_summary_enabled = attrs.get("summary_enabled", pre_summary_enabled)
        post_deleted = attrs.get("deleted", pre_deleted)

        pre_active = pre_summary_enabled and not pre_deleted
        post_active = post_summary_enabled and not post_deleted
        return post_active and not pre_active

    def _validate_summary_enabled_org_limit(self, organization) -> None:
        # Already-on subscriptions stay on for grandfathered orgs already over
        # the cap; the becoming-active check in validate() ensures we only get
        # here when the row is transitioning into the active-summary state.
        limit = get_organization_limit(
            organization=organization,
            key=LimitKey.MAX_ACTIVE_AI_SUMMARIES_PER_ORG,
        )
        if limit is None:
            return

        active_count = _count_active_summaries(organization)
        if active_count >= limit:
            self._capture_summary_cap_hit(organization, active_count, limit)
            raise QuotaLimitExceeded(
                f"Your plan allows up to {limit} active AI summaries. "
                "Disable an existing summary or upgrade your plan to add more."
            )

    def _caller_distinct_id(self) -> str:
        request = self.context.get("request")
        if request and getattr(request, "user", None) and getattr(request.user, "distinct_id", None):
            return str(request.user.distinct_id)
        return f"team_{self.context.get('team_id')}"

    def _capture_subscription_created(self, instance: Subscription) -> None:
        # Adoption telemetry: fires on every create (enabled or not) so we can see what
        # kind of subscription users build. Distinct from the slo_operation block below,
        # which only tracks the delivery-workflow trigger for enabled subscriptions.
        try:
            posthoganalytics.capture(
                distinct_id=self._caller_distinct_id(),
                event="subscription_created",
                properties={
                    "subscription_id": instance.id,
                    "team_id": instance.team_id,
                    "content_type": instance.content_type,
                    "target_type": instance.target_type,
                    "frequency": instance.frequency,
                    "enabled": instance.enabled,
                    "summary_enabled": instance.summary_enabled,
                },
                groups=groups(None, instance.team),
            )
        except Exception:
            # Telemetry must never poison the create path.
            pass

    def _capture_summary_cap_hit(self, organization, active_count: int, limit: int) -> None:
        # Rate-limited to one event per org per 10 minutes so a misbehaving
        # client retrying in a loop doesn't spam the analytics stream. Within
        # that window the user-visible 402 still fires every time.
        dedupe_key = _summary_cap_hit_dedupe_key(organization.id)
        if cache.get(dedupe_key):
            return
        cache.set(dedupe_key, True, SUMMARY_CAP_HIT_DEDUPE_TTL_SECONDS)

        try:
            posthoganalytics.capture(
                distinct_id=self._caller_distinct_id(),
                event="subscription_ai_summary_cap_hit",
                properties={
                    "team_id": self.context.get("team_id"),
                    "organization_id": str(organization.id),
                    "active_count": active_count,
                    "limit": limit,
                    "is_create": self.instance is None,
                },
                groups={"organization": str(organization.id)},
            )
        except Exception:
            # Telemetry must never poison the validation path.
            pass

    def _evaluate_feature_flag(self, flag_key: str) -> bool:
        """Evaluate a feature flag for the caller's organization.

        Scoped by organization (not user) so gates are stable across a team's
        members. `only_evaluate_locally=False` so we respect server-side cohort
        / property conditions — these checks aren't on a hot path.
        """
        request = self.context.get("request")
        if not request or not getattr(request, "user", None) or not getattr(request.user, "distinct_id", None):
            return False
        organization = self.context["get_organization"]()
        org_id = str(organization.id) if organization else ""
        return bool(
            posthoganalytics.feature_enabled(
                flag_key,
                str(request.user.distinct_id),
                groups={"organization": org_id},
                group_properties={"organization": {"id": org_id}},
                only_evaluate_locally=False,
            )
        )

    def _prompt_guide_feature_enabled(self) -> bool:
        return self._evaluate_feature_flag(SUBSCRIPTION_AI_SUMMARY_PROMPT_GUIDE_FEATURE_FLAG_KEY)

    def _validate_dashboard_export_subscription(self, attrs):
        dashboard = attrs.get("dashboard") or (self.instance.dashboard if self.instance else None)
        if dashboard is None:
            # Reject dashboard_export_insights on non dashboard subscriptions
            if attrs.get("dashboard_export_insights"):
                raise ValidationError(
                    {"dashboard_export_insights": ["Cannot set insights selection without a dashboard."]}
                )
            return

        # For PATCH requests, dashboard_export_insights might not be in attrs - only validate if provided or on create
        dashboard_export_insights_provided = "dashboard_export_insights" in attrs
        dashboard_export_insights = attrs.get("dashboard_export_insights", [])

        is_create = self.instance is None
        if (
            # For new dashboard subscriptions, require at least one insight to be selected
            (is_create and not dashboard_export_insights)
            or
            # If updating and explicitly setting dashboard_export_insights to empty, reject it
            (not is_create and dashboard_export_insights_provided and not dashboard_export_insights)
        ):
            raise ValidationError({"dashboard_export_insights": ["Select at least one insight for this subscription."]})

        if dashboard_export_insights:
            selected_ids = set(dashboard_export_insights)

            if len(selected_ids) > DEFAULT_MAX_ASSET_COUNT:
                raise ValidationError(
                    {"dashboard_export_insights": [f"Cannot select more than {DEFAULT_MAX_ASSET_COUNT} insights."]}
                )

            # Ensure all selected insights belong to the team
            if Insight.objects.filter(id__in=selected_ids, team_id=self.context["team_id"]).count() != len(
                selected_ids
            ):
                raise ValidationError(
                    {"dashboard_export_insights": ["Some insights do not belong to your team or do no longer exist."]}
                )

            # Ensure all selected insights belong to the dashboard (and are not deleted)
            dashboard_insight_ids = set(
                dashboard.tiles.filter(insight__isnull=False, insight__deleted=False).values_list(
                    "insight_id", flat=True
                )
            )
            invalid_ids = selected_ids - dashboard_insight_ids

            if invalid_ids:
                raise ValidationError(
                    {"dashboard_export_insights": [f"{len(invalid_ids)} invalid insight(s) selected."]}
                )

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> Subscription:
        request = self.context["request"]
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = request.user
        team = self.context["get_team"]()
        current_count = Subscription.objects.filter(team_id=team.id, deleted=False).count()
        check_count_limit(
            team=team,
            key=LimitKey.MAX_SUBSCRIPTIONS_PER_TEAM,
            current_count=current_count,
            user=request.user,
        )

        invite_message = validated_data.pop("invite_message", "")
        dashboard_export_insight_ids = validated_data.pop("dashboard_export_insights", [])
        instance: Subscription = super().create(validated_data)

        # Bust the org-wide active-summary count cache so the next quota
        # fetch reflects this row, regardless of summary_enabled — over-busting
        # is cheap and removes the need to track the prior state.
        _invalidate_summary_quota_cache(instance.team.organization_id)

        if dashboard_export_insight_ids:
            instance.dashboard_export_insights.set(dashboard_export_insight_ids)

        self._capture_subscription_created(instance)

        # Skip the workflow trigger when the new subscription is created in a disabled
        # state — mirrors the equivalent guard in `update()`. Avoids firing a delivery
        # for a subscription that won't fire on its schedule either.
        if not instance.enabled:
            return instance

        with slo_operation(
            spec=SloSpec(
                distinct_id=str(request.user.distinct_id),
                area=SloArea.ANALYTIC_PLATFORM,
                operation=SloOperation.SUBSCRIPTION_CREATE,
                team_id=instance.team_id,
                resource_id=str(instance.id),
            ),
            properties={
                "subscription_id": instance.id,
                "target_type": instance.target_type,
                "frequency": instance.frequency,
                "interval": instance.interval,
                "byweekday": instance.byweekday,
                "bysetpos": instance.bysetpos,
                "count": instance.count,
                "resource_type": "dashboard" if instance.dashboard_id else "insight" if instance.insight_id else None,
                "dashboard_export_insights_count": len(dashboard_export_insight_ids),
                "summary_enabled": instance.summary_enabled,
                "has_summary_prompt_guide": bool(instance.summary_prompt_guide),
                "has_until_date": instance.until_date is not None,
                "has_invite_message": bool(invite_message),
            },
        ):
            temporal = sync_connect()
            workflow_id = f"handle-subscription-value-change-{instance.id}-{uuid.uuid4()}"
            asyncio.run(
                temporal.start_workflow(
                    "handle-subscription-value-change",
                    ProcessSubscriptionWorkflowInputs(
                        subscription_id=instance.id,
                        team_id=instance.team_id,
                        distinct_id=str(instance.created_by.distinct_id)
                        if instance.created_by
                        else str(instance.team_id),
                        previous_value="",
                        invite_message=invite_message,
                        trigger_type=SubscriptionTriggerType.TARGET_CHANGE,
                    ),
                    id=workflow_id,
                    task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
                )
            )

        return instance

    def update(self, instance: Subscription, validated_data: dict, *args, **kwargs) -> Subscription:
        request = self.context["request"]
        previous_value = instance.target_value
        was_disabled = instance.enabled is False
        is_delete = not instance.deleted and validated_data.get("deleted") is True
        invite_message = validated_data.pop("invite_message", "")
        dashboard_export_insight_ids = validated_data.pop("dashboard_export_insights", [])

        if is_delete:
            with slo_operation(
                spec=SloSpec(
                    distinct_id=str(request.user.distinct_id),
                    area=SloArea.ANALYTIC_PLATFORM,
                    operation=SloOperation.SUBSCRIPTION_DELETE,
                    team_id=instance.team_id,
                    resource_id=str(instance.id),
                ),
                properties={
                    "subscription_id": instance.id,
                    "target_type": instance.target_type,
                    "frequency": instance.frequency,
                    "resource_type": "dashboard"
                    if instance.dashboard_id
                    else "insight"
                    if instance.insight_id
                    else None,
                },
            ):
                instance = super().update(instance, validated_data)
            _invalidate_summary_quota_cache(instance.team.organization_id)
            return instance

        instance = super().update(instance, validated_data)
        _invalidate_summary_quota_cache(instance.team.organization_id)

        if dashboard_export_insight_ids:
            instance.dashboard_export_insights.set(dashboard_export_insight_ids)

        # Re-enabling clears the stale next_delivery_date that was frozen while
        # disabled. Without this, the scheduler picks the sub up on its next tick
        # (the past date matches `next_delivery_date__lte=now`) and fires a second
        # SCHEDULED delivery right after the immediate TARGET_CHANGE confirmation.
        if was_disabled and instance.enabled:
            instance.set_next_delivery_date()
            instance.save(update_fields=["next_delivery_date"])

        # Skip the workflow trigger when the resulting state is disabled. No delivery
        # should fire for a disabled subscription regardless of whether it was just
        # disabled or already disabled. Re-enabling (`enabled: false → true`) DOES
        # trigger the workflow so the user gets immediate confirmation delivery.
        if not instance.enabled:
            return instance

        temporal = sync_connect()
        workflow_id = f"handle-subscription-value-change-{instance.id}-{uuid.uuid4()}"
        asyncio.run(
            temporal.start_workflow(
                "handle-subscription-value-change",
                ProcessSubscriptionWorkflowInputs(
                    subscription_id=instance.id,
                    team_id=instance.team_id,
                    distinct_id=str(instance.created_by.distinct_id) if instance.created_by else str(instance.team_id),
                    previous_value=previous_value,
                    invite_message=invite_message,
                    trigger_type=SubscriptionTriggerType.TARGET_CHANGE,
                ),
                id=workflow_id,
                task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
            )
        )

        return instance


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(
                name="created_by",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by creator user UUID.",
            ),
            OpenApiParameter(
                name="resource_type",
                type=str,
                enum=["insight", "dashboard", "ai_prompt"],
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by subscription resource: insight, dashboard export, or AI report.",
            ),
            OpenApiParameter(
                name="target_type",
                type=str,
                enum=[m.value for m in Subscription.SubscriptionTarget],
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by delivery channel (email, Slack, or webhook).",
            ),
            OpenApiParameter(
                name="insight",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by insight ID.",
            ),
            OpenApiParameter(
                name="dashboard",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by dashboard ID.",
            ),
        ],
    ),
)
@extend_schema(tags=["subscriptions"])
class SubscriptionViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "subscription"
    queryset = Subscription.objects.all()
    serializer_class = SubscriptionSerializer
    permission_classes = [PremiumFeaturePermission]
    premium_feature = AvailableFeature.SUBSCRIPTIONS
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        "title",
        "insight__name",
        "insight__derived_name",
        "dashboard__name",
    ]
    ordering_fields = [
        "created_at",
        "next_delivery_date",
        "title",
        "created_by__email",
    ]
    ordering = ["-created_at"]

    def safely_get_queryset(self, queryset) -> QuerySet:
        request_params = self.request.GET.dict()

        # Prefetch dashboard_export_insights to avoid N+1 queries in list/detail views
        queryset = queryset.prefetch_related("dashboard_export_insights")

        if self.action == "list":
            queryset = queryset.select_related("insight", "dashboard", "created_by")

            if "deleted" not in request_params:
                queryset = queryset.filter(deleted=False)

            created_by = request_params.get("created_by")
            if created_by:
                try:
                    uuid.UUID(created_by)
                except ValueError:
                    raise ValidationError({"created_by": ["Not a valid UUID."]}) from None
                queryset = queryset.filter(created_by__uuid=created_by)

            resource_type = request_params.get("resource_type")
            if resource_type == "insight":
                queryset = queryset.filter(insight_id__isnull=False)
            elif resource_type == "dashboard":
                queryset = queryset.filter(dashboard_id__isnull=False)
            elif resource_type == "ai_prompt":
                queryset = queryset.filter(content_type=Subscription.ContentType.AI_PROMPT)

            target_type_filter = request_params.get("target_type")
            if target_type_filter:
                if target_type_filter not in Subscription.SubscriptionTarget.values:
                    raise ValidationError(
                        {
                            "target_type": [
                                f"Must be one of: {', '.join(sorted(Subscription.SubscriptionTarget.values))}."
                            ]
                        }
                    )
                queryset = queryset.filter(target_type=target_type_filter)

        for key in request_params:
            if key == "insight":
                queryset = queryset.filter(insight_id=request_params["insight"])
            elif key == "dashboard":
                queryset = queryset.filter(dashboard_id=request_params["dashboard"])
            elif key == "deleted":
                queryset = queryset.filter(deleted=str_to_bool(request_params["deleted"]))

        return queryset

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(
                description=(
                    "Org-wide AI summary quota: count of currently-active summaries and the limit "
                    "for the org's plan tier. `limit` is null when no cap is configured."
                ),
                response={
                    "type": "object",
                    "properties": {
                        "active_count": {"type": "integer"},
                        "limit": {"type": "integer", "nullable": True},
                        "at_limit": {"type": "boolean"},
                    },
                    "required": ["active_count", "limit", "at_limit"],
                },
            )
        },
    )
    @action(
        methods=["GET"],
        detail=False,
        url_path="summary_quota",
        required_scopes=["subscription:read"],
    )
    def summary_quota(self, request, **kwargs):
        organization = self.organization
        cache_key = _summary_quota_cache_key(organization.id)
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)

        active_count = _count_active_summaries(organization)
        limit = get_organization_limit(
            organization=organization,
            key=LimitKey.MAX_ACTIVE_AI_SUMMARIES_PER_ORG,
        )
        payload = {
            "active_count": active_count,
            "limit": limit,
            "at_limit": limit is not None and active_count >= limit,
        }
        cache.set(cache_key, payload, SUMMARY_QUOTA_CACHE_TTL_SECONDS)
        return Response(payload)

    @extend_schema(
        request=AiReportRequestSerializer,
        responses={
            200: AiReportResponseSerializer,
            400: OpenApiResponse(description="Validation failed (e.g. prompt empty or oversized)"),
            403: OpenApiResponse(description="AI subscriptions not enabled for this organization"),
        },
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="ai_report",
        throttle_classes=[SubscriptionTestDeliveryThrottle],
        # query:read in addition to subscription:write — the response returns
        # LLM-summarized HogQL results, so a subscription-only token must not reach it.
        required_scopes=["subscription:write", "query:read"],
    )
    def ai_report(self, request, **kwargs):
        """Generate an ad-hoc AI report from a prompt without creating a recurring subscription.

        Runs the same planner → HogQL → synthesis pipeline as a scheduled AI subscription
        and returns the rendered markdown. Subject to the same cloud + consent + feature-flag
        gates as creating an AI subscription. Each call burns LLM tokens — throttled.
        """
        # Same gate set as `SubscriptionSerializer` AI create, with response shape
        # adapted: ValidationError there → 403 Response here. Helper-driven so a
        # new gate (e.g. quota) only needs adding in one place.
        gate_reason = _ai_create_gate_reason(self.organization, kind="reports", verb="generating")
        if gate_reason is not None:
            return Response({"detail": gate_reason}, status=status.HTTP_403_FORBIDDEN)

        serializer = AiReportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            markdown = generate_ai_report(
                team=self.team,
                user=request.user,
                prompt=serializer.validated_data["prompt"],
                window_days=serializer.validated_data["window_days"],
                ai_config=serializer.validated_data.get("ai_config"),
                trace_correlation_id=f"adhoc-team-{self.team.id}",
            )
        except PromptRejectedError as exc:
            raise ValidationError({"prompt": [str(exc)]})
        except AiReportStageError as exc:
            # Transient pipeline failure (planner/query/synthesis). 503 signals "retry";
            # naming the stage helps the caller understand what failed.
            return Response(
                {"detail": f"Report generation failed at the {exc.stage} stage. Please try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response({"markdown": markdown})

    @extend_schema(
        request=None,
        responses={202: OpenApiResponse(description="Test delivery workflow started")},
    )
    @action(
        methods=["POST"],
        detail=True,
        url_path="test-delivery",
        throttle_classes=[SubscriptionTestDeliveryThrottle],
        required_scopes=["subscription:write"],
    )
    def test_delivery(self, request, **kwargs):
        subscription = self.get_object()
        if subscription.deleted:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not subscription.enabled:
            return Response(
                {"detail": "Subscription is disabled. Re-enable it before sending a test delivery."},
                status=status.HTTP_409_CONFLICT,
            )

        temporal = sync_connect()
        workflow_id = f"test-delivery-subscription-{subscription.id}"
        try:
            asyncio.run(
                temporal.start_workflow(
                    "handle-subscription-value-change",
                    ProcessSubscriptionWorkflowInputs(
                        subscription_id=subscription.id,
                        team_id=subscription.team_id,
                        distinct_id=str(subscription.created_by.distinct_id)
                        if subscription.created_by
                        else str(subscription.team_id),
                        previous_value=None,
                        invite_message=None,
                        trigger_type=SubscriptionTriggerType.MANUAL,
                    ),
                    id=workflow_id,
                    task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
                )
            )
        except WorkflowAlreadyStartedError:
            return Response(
                {"detail": "Delivery already in progress"},
                status=status.HTTP_409_CONFLICT,
            )
        except Exception as e:
            capture_exception(e)
            return Response(
                {"detail": "Failed to schedule delivery"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        posthoganalytics.capture(
            distinct_id=str(request.user.distinct_id),
            event="subscription_test_delivery_scheduled",
            properties={
                "subscription_id": subscription.id,
                "team_id": subscription.team_id,
                "target_type": subscription.target_type,
                "insight_id": subscription.insight_id,
                "dashboard_id": subscription.dashboard_id,
                "temporal_workflow_id": workflow_id,
            },
            groups=groups(None, subscription.team),
        )

        return Response(status=status.HTTP_202_ACCEPTED)


class SubscriptionDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionDelivery
        fields = [
            "id",
            "subscription",
            "temporal_workflow_id",
            "idempotency_key",
            "trigger_type",
            "scheduled_at",
            "target_type",
            "target_value",
            "exported_asset_ids",
            "content_snapshot",
            "recipient_results",
            "status",
            "error",
            "created_at",
            "last_updated_at",
            "finished_at",
            "change_summary",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Primary key for this delivery row."},
            "subscription": {"help_text": "Parent subscription id."},
            "temporal_workflow_id": {"help_text": "Temporal workflow id for this delivery run."},
            "idempotency_key": {"help_text": "Dedupes activity retries for the same logical run."},
            "trigger_type": {"help_text": "Why the run started (e.g. scheduled, manual, target_change)."},
            "scheduled_at": {"help_text": "Planned send time when applicable."},
            "target_type": {"help_text": "Channel snapshot at send time (email, slack, webhook)."},
            "target_value": {"help_text": "Destination snapshot at send time (emails, channel id, URL)."},
            "exported_asset_ids": {"help_text": "ExportedAsset ids generated for this send."},
            "content_snapshot": {
                "help_text": (
                    "Snapshot at send time: dashboard metadata, total_insight_count, and per-exported-insight "
                    "entries (id, short_id, name, query_hash, cache_key, query_results, optional query_error)."
                )
            },
            "recipient_results": {
                "help_text": "Per-destination outcomes; items use status success, failed, or partial."
            },
            "status": {"help_text": "Overall run status: starting, completed, failed, or skipped."},
            "error": {"help_text": "Top-level failure payload when status is failed, if any."},
            "created_at": {"help_text": "When the delivery row was created."},
            "last_updated_at": {"help_text": "Last ORM update to this row."},
            "finished_at": {"help_text": "When the run finished, if applicable."},
            "change_summary": {"help_text": "AI-generated summary included in this delivery, when one was produced."},
        }


class SubscriptionDeliveryCursorPagination(CursorPagination):
    page_size = 50
    ordering = "-created_at"


@extend_schema_view(
    list=extend_schema(
        summary="List subscription deliveries",
        description="Paginated delivery history for a subscription. Requires premium subscriptions.",
        parameters=[
            OpenApiParameter(
                name="status",
                type=str,
                enum=[m.value for m in SubscriptionDelivery.Status],
                location=OpenApiParameter.QUERY,
                required=False,
                description="Return only deliveries in this run status (starting, completed, failed, or skipped).",
            ),
        ],
        responses={200: OpenApiResponse(response=SubscriptionDeliverySerializer(many=True))},
    ),
    retrieve=extend_schema(
        summary="Retrieve subscription delivery",
        description="Fetch one delivery row by id.",
        responses={200: SubscriptionDeliverySerializer},
    ),
)
@extend_schema(tags=["core"])
class SubscriptionDeliveryViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "subscription"
    queryset = SubscriptionDelivery.objects.all()
    serializer_class = SubscriptionDeliverySerializer
    permission_classes = [PremiumFeaturePermission]
    premium_feature = AvailableFeature.SUBSCRIPTIONS
    pagination_class = SubscriptionDeliveryCursorPagination
    ordering = "-created_at"

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        subscription_id = self.kwargs.get("parent_lookup_subscription_id")
        if subscription_id:
            queryset = queryset.filter(subscription_id=subscription_id)
        if self.action == "list":
            status_param = self.request.query_params.get("status")
            if status_param:
                valid = {c.value for c in SubscriptionDelivery.Status}
                if status_param not in valid:
                    raise ValidationError(
                        {"status": [f"Must be one of: {', '.join(sorted(valid))}."]},
                    )
                queryset = queryset.filter(status=status_param)
        return queryset


def unsubscribe(request: HttpRequest):
    token = request.GET.get("token")
    if not token:
        return JsonResponse({"success": False})

    try:
        unsubscribe_using_token(token)
    except jwt.DecodeError:
        return JsonResponse({"success": False})

    return JsonResponse({"success": True})
