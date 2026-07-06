import uuid
import asyncio
from collections.abc import Callable
from typing import Any, ClassVar, Optional

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
)
from posthog.event_usage import get_request_analytics_properties, groups
from posthog.exceptions import QuotaLimitExceeded
from posthog.exceptions_capture import capture_exception
from posthog.models.integration import Integration
from posthog.rate_limit import SubscriptionTestDeliveryThrottle
from posthog.resource_limits import LimitKey, check_count_limit, get_organization_limit
from posthog.slo.context import SloSpec, slo_operation
from posthog.slo.types import SloArea, SloOperation
from posthog.temporal.common.client import sync_connect
from posthog.utils import str_to_bool

from products.exports.backend.models.subscription import (
    Subscription,
    SubscriptionDelivery,
    attribute_subscription_saves,
    unsubscribe_using_token,
)
from products.exports.backend.temporal.subscriptions.ai_subscription.spec_generator import (
    PROMPT_MAX_LENGTH as AI_PROMPT_MAX_LENGTH,
    PromptRejectedError,
    sanitize_prompt,
)
from products.exports.backend.temporal.subscriptions.types import (
    AI_REPORT_DIAGNOSTICS_KEY,
    AI_REPORT_PROMPT_SNAPSHOT_KEY,
    AI_REPORT_SNAPSHOT_KEY,
    ProcessSubscriptionWorkflowInputs,
    SubscriptionTriggerType,
)
from products.product_analytics.backend.models.insight import Insight

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited
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


def _ai_create_gate_reason(organization, distinct_id: str) -> Optional[str]:
    if not settings.DEBUG and not is_cloud():
        return "AI subscriptions are only available in PostHog Cloud."
    if not organization.is_ai_data_processing_approved:
        return "Your organization must approve AI data processing before creating AI subscriptions."
    # Per-user gate so people can self-enable via feature previews (early access) — the flag is
    # person-based. AI credits and the subscription limit stay org-scoped, enforced separately.
    # Non-user callers get a synthetic team_<id> distinct_id that never matches → fails closed.
    if not posthoganalytics.feature_enabled(
        SUBSCRIPTION_AI_PROMPT_FEATURE_FLAG_KEY,
        distinct_id,
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    ):
        return "AI subscriptions are not enabled for your account."
    return None


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

    FIELDS_THAT_TRIGGER_REDELIVERY: ClassVar[tuple[str, ...]] = (
        "target_value",
        "target_type",
        "integration_id",
        "prompt",
        "insight_id",
        "dashboard_id",
    )

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
    resource_type = serializers.ChoiceField(
        choices=Subscription.ResourceType.choices,
        read_only=True,
        help_text=(
            "What the subscription delivers: 'insight' (snapshot of one insight), "
            "'dashboard' (snapshot of one dashboard), or 'ai_prompt' (LLM-generated report). "
            "Read-only — derived from the populated target (insight → insight, "
            "dashboard → dashboard, prompt → ai_prompt)."
        ),
    )

    class Meta:
        model = Subscription
        fields = [
            "id",
            "resource_type",
            "dashboard",
            "insight",
            "insight_short_id",
            "resource_name",
            "dashboard_export_insights",
            "prompt",
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
            "prompt": {
                "help_text": (
                    "Free-text prompt that drives the AI-generated report. Required when "
                    "resource_type is 'ai_prompt'. Max 4000 characters."
                ),
            },
            "dashboard": {"help_text": "Dashboard ID to subscribe to (mutually exclusive with insight on create)."},
            "insight": {"help_text": "Insight ID to subscribe to (mutually exclusive with dashboard on create)."},
            "target_type": {"help_text": "Delivery channel: email or slack."},
            "target_value": {
                "help_text": "Recipient(s): comma-separated email addresses for email, or Slack channel name/ID for slack."
            },
            "frequency": {"help_text": "How often to deliver: daily, weekly, monthly, or yearly."},
            "interval": {
                "required": True,
                "min_value": 1,
                "help_text": (
                    "Interval multiplier (e.g. 2 with weekly frequency means every 2 weeks). "
                    "Required on create; must be 1 or greater."
                ),
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
            "summary_enabled": {
                "help_text": (
                    "Whether to attach an AI-generated summary to each delivery (insight and dashboard "
                    "subscriptions only). Requires the organization to have approved AI data processing, and "
                    "is subject to the org's active-summary cap and AI credit budget; otherwise the write is "
                    "rejected. Not applicable to prompt subscriptions, which are themselves AI-generated."
                ),
            },
            "summary_prompt_guide": {
                "help_text": (
                    "Optional free-text guidance (max 500 chars) steering the AI summary, e.g. which metrics "
                    "to emphasize. Only settable when AI summary context is enabled for the organization; "
                    "clearing it (empty string) is always allowed."
                ),
            },
        }

    def get_insight_short_id(self, obj: Subscription) -> Optional[str]:
        if obj.insight_id and obj.insight is not None:
            return obj.insight.short_id
        return None

    def get_resource_name(self, obj: Subscription) -> Optional[str]:
        info = obj.resource_info
        return info.name if info else None

    def _validate_insight_content(self, attrs: dict, existing: Optional[Subscription]) -> None:
        if not (attrs.get("insight") or (existing and existing.insight_id)):
            raise ValidationError({"insight": ["Insight is required for insight subscriptions."]})
        if attrs.get("dashboard") or attrs.get("prompt"):
            raise ValidationError({"insight": ["Insight subscriptions cannot also set dashboard or prompt."]})

    def _validate_dashboard_content(self, attrs: dict, existing: Optional[Subscription]) -> None:
        if not (attrs.get("dashboard") or (existing and existing.dashboard_id)):
            raise ValidationError({"dashboard": ["Dashboard is required for dashboard subscriptions."]})
        if attrs.get("insight") or attrs.get("prompt"):
            raise ValidationError({"dashboard": ["Dashboard subscriptions cannot also set insight or prompt."]})

    def _validate_ai_content(self, attrs: dict, existing: Optional[Subscription]) -> None:
        if attrs.get("insight") or attrs.get("dashboard"):
            raise ValidationError({"prompt": ["AI subscriptions cannot also set insight or dashboard."]})
        # Explicit-key check so a PATCH sending prompt="" doesn't fall through to the stale value.
        prompt = (attrs["prompt"] if "prompt" in attrs else (existing.prompt if existing else None)) or ""
        prompt = prompt.strip()
        if not prompt:
            raise ValidationError({"prompt": ["Prompt is required for AI subscriptions."]})
        if len(prompt) > AI_PROMPT_MAX_LENGTH:
            raise ValidationError({"prompt": [f"Prompt cannot exceed {AI_PROMPT_MAX_LENGTH} characters."]})
        if "prompt" in attrs:
            attrs["prompt"] = prompt
        target_type = attrs.get("target_type") or (existing.target_type if existing else None)
        if target_type and target_type not in (
            Subscription.SubscriptionTarget.EMAIL,
            Subscription.SubscriptionTarget.SLACK,
        ):
            raise ValidationError({"target_type": ["AI subscriptions only support email or slack delivery."]})
        # Gates fire on create only; existing AI subs stay editable.
        if existing is None:
            gate_reason = _ai_create_gate_reason(self.context["get_organization"](), self._caller_distinct_id())
            if gate_reason is not None:
                raise ValidationError(gate_reason)

    def validate(self, attrs):
        request = self.context.get("request")
        # Re-run the free-tier cap on create AND on restore (deleted: true → false) —
        # a soft-deleted row frees its slot, so PATCHing one back to active re-occupies
        # one and must respect the limit, otherwise a free-tier team could soft-delete +
        # create + restore its way past the cap.
        is_create = request is not None and request.method == "POST"
        is_restoring = self.instance is not None and self.instance.deleted and attrs.get("deleted") is False
        if is_create or is_restoring:
            msg = Subscription.check_subscription_limit(self.context["team_id"], self.context["get_organization"]())
            if msg:
                raise ValidationError({"subscription": [msg]})

        existing = self.instance

        if attrs.get("dashboard") and attrs["dashboard"].team.id != self.context["team_id"]:
            raise ValidationError({"dashboard": ["This dashboard does not belong to your team."]})

        if attrs.get("insight") and attrs["insight"].team.id != self.context["team_id"]:
            raise ValidationError({"insight": ["This insight does not belong to your team."]})

        if existing is None:
            # Create: a subscription must export an insight, a dashboard, or an AI prompt.
            if not attrs.get("dashboard") and not attrs.get("insight") and not attrs.get("prompt"):
                raise ValidationError("A subscription must have an insight, a dashboard, or a prompt.")

        try:
            if existing is not None:
                # `resource_type` derives from the row's content; a corrupt row (e.g. a prompt
                # nulled directly in the DB) leaves nothing to derive from and raises.
                resource_type = existing.resource_type
            else:
                insight, dashboard = attrs.get("insight"), attrs.get("dashboard")
                resource_type = Subscription.derive_resource_type(
                    insight.id if insight else None, dashboard.id if dashboard else None, attrs.get("prompt")
                )
        except ValueError as exc:
            raise ValidationError(str(exc))
        content_validators: dict[str, Callable[[dict, Optional[Subscription]], None]] = {
            Subscription.ResourceType.INSIGHT: self._validate_insight_content,
            Subscription.ResourceType.DASHBOARD: self._validate_dashboard_content,
            Subscription.ResourceType.AI_PROMPT: self._validate_ai_content,
        }
        validate_for_resource_type = content_validators.get(resource_type)
        # Fail soft on an unexpected resource_type (e.g. a stale DB row) — a 400 is
        # diagnosable, an unhandled KeyError surfaces as a 500.
        if validate_for_resource_type is None:
            raise ValidationError({"resource_type": [f"Unsupported resource_type: {resource_type}."]})
        validate_for_resource_type(attrs, existing)

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
            if resource_type == Subscription.ResourceType.AI_PROMPT:
                prompt_after = attrs.get("prompt") if "prompt" in attrs else (existing.prompt if existing else None)
                created_by_after = existing.created_by if existing else None
                if created_by_after is None:
                    raise ValidationError(
                        {"enabled": ["Cannot re-enable AI subscription: the original creator is unavailable."]}
                    )
                try:
                    sanitize_prompt(prompt_after)
                except PromptRejectedError as exc:
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
            self._validate_summary_credit_budget()
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

    def _validate_summary_credit_budget(self) -> None:
        # Refuse to turn a summary on while the org is over its AI credit budget,
        # mirroring the chat assistant's gate (ee/api/conversation.py).
        team = self.context["get_team"]()
        if is_team_limited(team.api_token, QuotaResource.AI_CREDITS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY):
            raise QuotaLimitExceeded(
                "Your organization reached its AI credit usage limit. "
                "Increase the limits in Billing settings, or ask an org admin to do so."
            )

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

    def _capture_update_delivery_decision(
        self, instance: Subscription, *, delivery_triggered: bool, re_enabled: bool
    ) -> None:
        try:
            posthoganalytics.capture(
                distinct_id=self._caller_distinct_id(),
                event="subscription_update_delivery_decision",
                properties={
                    "subscription_id": instance.id,
                    "team_id": instance.team_id,
                    "resource_type": instance.resource_type,
                    "target_type": instance.target_type,
                    "delivery_triggered": delivery_triggered,
                    "reason": "re_enabled"
                    if re_enabled
                    else ("delivery_field_changed" if delivery_triggered else "no_delivery_relevant_change"),
                },
                groups=groups(None, instance.team),
            )
        except Exception as e:
            # Telemetry must never block the update.
            capture_exception(e)

    def _evaluate_feature_flag(self, flag_key: str) -> bool:
        """Evaluate a feature flag for the caller's organization.

        Scoped by organization (not user) so gates are stable across a team's
        members. `only_evaluate_locally=False` so we respect server-side cohort
        / property conditions — these checks aren't on a hot path.
        (`_ai_create_gate_reason` is intentionally person-scoped instead — it
        backs a per-user early-access opt-in — so don't unify the two.)
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
        with attribute_subscription_saves(get_request_analytics_properties(request)):
            instance: Subscription = super().create(validated_data)

        # Bust the org-wide active-summary count cache so the next quota
        # fetch reflects this row, regardless of summary_enabled — over-busting
        # is cheap and removes the need to track the prior state.
        _invalidate_summary_quota_cache(instance.team.organization_id)

        if dashboard_export_insight_ids:
            instance.dashboard_export_insights.set(dashboard_export_insight_ids)

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
                "resource_type": instance.resource_type,
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
                        resource_type=instance.resource_type,
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
        # Track payload PRESENCE, not truthiness: an empty list (clearing all exports) is delivery-relevant
        # too, so `bool(ids)` would miss it. Pop loses presence, so capture it first.
        export_insights_in_payload = "dashboard_export_insights" in validated_data
        dashboard_export_insight_ids = validated_data.pop("dashboard_export_insights", [])
        analytics_props = get_request_analytics_properties(request)

        # Snapshot delivery-relevant scalar values before the write so we can tell, after,
        # whether the edit actually changed what gets delivered. Only snapshot the
        # dashboard_export_insights M2M when the payload carries it — that's the only case
        # `.set()` can mutate the relation, so a schedule/meta-only edit pays no M2M query.
        old_delivery_values = {field: getattr(instance, field) for field in self.FIELDS_THAT_TRIGGER_REDELIVERY}
        old_export_insight_ids = (
            set(instance.dashboard_export_insights.values_list("id", flat=True)) if export_insights_in_payload else None
        )

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
                    "resource_type": instance.resource_type,
                },
            ):
                with attribute_subscription_saves(analytics_props):
                    instance = super().update(instance, validated_data)
            _invalidate_summary_quota_cache(instance.team.organization_id)
            return instance

        with attribute_subscription_saves(analytics_props):
            instance = super().update(instance, validated_data)
        _invalidate_summary_quota_cache(instance.team.organization_id)

        # Apply the M2M whenever the field is in the payload — including an empty list, which clears it.
        if export_insights_in_payload:
            instance.dashboard_export_insights.set(dashboard_export_insight_ids)

        is_re_enabling = was_disabled and instance.enabled

        # Re-enabling clears the stale next_delivery_date that was frozen while
        # disabled. Without this, the scheduler picks the sub up on its next tick
        # (the past date matches `next_delivery_date__lte=now`) and fires a second
        # SCHEDULED delivery right after the immediate TARGET_CHANGE confirmation.
        if is_re_enabling:
            instance.set_next_delivery_date()
            instance.save(update_fields=["next_delivery_date"])

        # Skip the workflow trigger when the resulting state is disabled. No delivery
        # should fire for a disabled subscription regardless of whether it was just
        # disabled or already disabled.
        if not instance.enabled:
            return instance

        # Only fire the immediate confirmation delivery when the edit changed *what*
        # gets delivered, or when re-enabling (`enabled: false → true`) — the user
        # expects a confirmation delivery in both cases. A schedule/meta-only edit
        # (frequency, interval, title, summary_*, …) re-saves next_delivery_date via
        # the model's save() but must not push a fresh delivery.
        delivery_target_changed = any(
            getattr(instance, field) != old_value for field, old_value in old_delivery_values.items()
        ) or (old_export_insight_ids is not None and set(dashboard_export_insight_ids) != old_export_insight_ids)

        # The "<kind> subscription updated" event fires from the post_save signal before this decision is
        # made, so it can't tell an edit that fired a confirmation from one that intentionally skipped.
        # Emit the decision explicitly so a regression that silently suppressed deliveries stays observable.
        delivery_triggered = is_re_enabling or delivery_target_changed
        self._capture_update_delivery_decision(
            instance, delivery_triggered=delivery_triggered, re_enabled=is_re_enabling
        )
        if not delivery_triggered:
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
                    resource_type=instance.resource_type,
                ),
                id=workflow_id,
                task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
            )
        )

        return instance


def _subscription_is_ai_prompt(subscription_id: str | int, team_id: int) -> bool:
    """An AI subscription is one backed by a non-empty prompt (team-scoped)."""
    return (
        Subscription.objects.filter(pk=subscription_id, team_id=team_id)
        .exclude(prompt__isnull=True)
        .exclude(prompt="")
        .exists()
    )


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
                description="Filter by delivery channel (email or Slack).",
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

    # Writing an AI prompt subscription also requires query-read access: it runs LLM-generated
    # HogQL and delivers the results, so subscription:write alone could exfiltrate analytics.
    # Two layers gate this off _write_touches_ai_subscription: a required query:read scope keeps a
    # token least-privileged, and the RBAC check in check_permissions enforces actual query access
    # for every write — a scope is only a capability flag, not proof of RBAC (personal keys can
    # carry query:read without it), and session auth has no scopes at all.
    def dangerously_get_required_scopes(self, request, view) -> list[str] | None:
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None
        scopes = [f"{self.scope_object}:write"]
        if self._write_touches_ai_subscription(request, view):
            scopes.append("query:read")
        return scopes

    def check_permissions(self, request) -> None:
        super().check_permissions(request)
        # Enforce query-viewer RBAC for every AI-prompt write, regardless of auth: the query:read
        # scope above gates tokens but does not prove the owner has query access, and session auth
        # bypasses scopes entirely.
        if (
            request.method not in ("GET", "HEAD", "OPTIONS")
            and self._write_touches_ai_subscription(request, self)
            and not self.user_access_control.check_access_level_for_resource("query", "viewer")
        ):
            raise exceptions.PermissionDenied("You need query access to create or deliver AI prompt subscriptions.")

    def _write_touches_ai_subscription(self, request, view) -> bool:
        if request.data.get("prompt"):  # create (or a body that sets a prompt)
            return True
        # Existing subscription (update / test-delivery): resolve its kind by pk, team-scoped.
        pk = view.kwargs.get("pk")
        return bool(pk) and _subscription_is_ai_prompt(pk, self.team_id)

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
                queryset = queryset.filter(prompt__isnull=False).exclude(prompt="")

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
        request=None,
        responses={202: OpenApiResponse(description="Test delivery workflow started")},
    )
    @action(
        methods=["POST"],
        detail=True,
        url_path="test-delivery",
        throttle_classes=[SubscriptionTestDeliveryThrottle],
        # Scope is resolved dynamically in dangerously_get_required_scopes so AI subscriptions
        # also require query:read (test-delivery runs the AI HogQL pipeline). A static
        # required_scopes here would short-circuit that check.
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
                        resource_type=subscription.resource_type,
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
                **get_request_analytics_properties(request),
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


class AIReportQueryDiagnosticSerializer(serializers.Serializer):
    # Per-step query diagnostics persisted alongside the report markdown. Query-derived (the generated
    # HogQL is here), so it is scrubbed for callers without query access — never shipped to recipients.
    description = serializers.CharField(help_text="What this query step was meant to compute.")
    hogql = serializers.CharField(help_text="The HogQL the assistant generated for this step.")
    ok = serializers.BooleanField(help_text="Whether the query ran successfully.")
    error_type = serializers.CharField(
        allow_null=True, help_text="Exception class name when the query failed; null on success."
    )
    human_readable_error = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Human-readable failure reason, present only for query errors safe to surface to the "
        "subscription owner (e.g. an unresolved field name); null on success and for internal errors, "
        "which expose error_type only.",
    )


class SubscriptionDeliverySerializer(serializers.ModelSerializer):
    # Delivery fields that embed the query-derived AI report, mapped to the value each returns when
    # scrubbed for a caller without query access (content_snapshot is a non-null object, the rest
    # nullable). Single source of truth — keep in sync when adding AI-derived delivery fields.
    # ai_report_prompt is user-authored (not query-derived) and already readable on the parent
    # subscription, so it is intentionally not scrubbed.
    AI_REPORT_SCRUBBED: ClassVar[dict[str, object | None]] = {
        "content_snapshot": {},
        "change_summary": None,
        "ai_report": None,
        "ai_report_diagnostics": None,
    }

    ai_report = serializers.SerializerMethodField(
        help_text="AI-generated report markdown delivered by this run. Null for non-AI deliveries or runs without a persisted report."
    )
    ai_report_diagnostics = serializers.SerializerMethodField(
        help_text="Per-step query diagnostics (generated HogQL + failure type) for this report. Null for non-AI deliveries or runs without persisted diagnostics."
    )
    ai_report_prompt = serializers.SerializerMethodField(
        help_text="The subscription's prompt as it was when this report was generated. Null for older deliveries and non-AI deliveries."
    )

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
            "ai_report",
            "ai_report_diagnostics",
            "ai_report_prompt",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Primary key for this delivery row."},
            "subscription": {"help_text": "Parent subscription id."},
            "temporal_workflow_id": {"help_text": "Temporal workflow id for this delivery run."},
            "idempotency_key": {"help_text": "Dedupes activity retries for the same logical run."},
            "trigger_type": {"help_text": "Why the run started (e.g. scheduled, manual, target_change)."},
            "scheduled_at": {"help_text": "Planned send time when applicable."},
            "target_type": {"help_text": "Channel snapshot at send time (email or slack)."},
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

    def _content_snapshot_text(self, delivery: SubscriptionDelivery, key: str) -> Optional[str]:
        snapshot = delivery.content_snapshot
        if not isinstance(snapshot, dict):
            return None
        value = snapshot.get(key)
        return value if isinstance(value, str) and value else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_ai_report(self, delivery: SubscriptionDelivery) -> Optional[str]:
        return self._content_snapshot_text(delivery, AI_REPORT_SNAPSHOT_KEY)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_ai_report_prompt(self, delivery: SubscriptionDelivery) -> Optional[str]:
        return self._content_snapshot_text(delivery, AI_REPORT_PROMPT_SNAPSHOT_KEY)

    @extend_schema_field(AIReportQueryDiagnosticSerializer(many=True, allow_null=True))
    def get_ai_report_diagnostics(self, delivery: SubscriptionDelivery) -> Optional[list[dict]]:
        snapshot = delivery.content_snapshot
        if not isinstance(snapshot, dict):
            return None
        diagnostics = snapshot.get(AI_REPORT_DIAGNOSTICS_KEY)
        return diagnostics if isinstance(diagnostics, list) else None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # The viewset sets this flag when an AI prompt delivery is read by a caller without query
        # access; scrub the query-derived report so subscription:read (or a self-granted query:read
        # scope) can't read analytics the user isn't allowed to run themselves. ai_report_prompt is
        # user-authored and already readable on the subscription, so it is deliberately not scrubbed.
        if self.context.get("hide_ai_report"):
            data.update(self.AI_REPORT_SCRUBBED)
            return data
        # The AI report now ships via the typed ai_report / ai_report_diagnostics / ai_report_prompt
        # fields, so drop the same keys from content_snapshot to avoid shipping the report twice.
        # The non-AI scaffold (insights, dashboard, total_insight_count) stays intact.
        snapshot = data.get("content_snapshot")
        if isinstance(snapshot, dict) and (
            AI_REPORT_SNAPSHOT_KEY in snapshot
            or AI_REPORT_PROMPT_SNAPSHOT_KEY in snapshot
            or AI_REPORT_DIAGNOSTICS_KEY in snapshot
        ):
            data["content_snapshot"] = {
                key: value
                for key, value in snapshot.items()
                if key not in (AI_REPORT_SNAPSHOT_KEY, AI_REPORT_PROMPT_SNAPSHOT_KEY, AI_REPORT_DIAGNOSTICS_KEY)
            }
        return data


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
@extend_schema(tags=["subscriptions"])
class SubscriptionDeliveryViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "subscription"
    queryset = SubscriptionDelivery.objects.all()
    serializer_class = SubscriptionDeliverySerializer
    pagination_class = SubscriptionDeliveryCursorPagination
    ordering = "-created_at"

    def get_serializer_context(self) -> dict:
        context = super().get_serializer_context()
        context["hide_ai_report"] = self._should_hide_ai_report()
        return context

    def _should_hide_ai_report(self) -> bool:
        # An AI prompt subscription's delivered report is query-derived, so reading it requires query
        # access — mirroring the create/test-delivery gate. Non-AI deliveries are unaffected.
        subscription_id = self.kwargs.get("parent_lookup_subscription_id")
        if not subscription_id:
            return True  # nested route always supplies this; fail closed (scrub) if it ever doesn't
        if not _subscription_is_ai_prompt(subscription_id, self.team_id):
            return False
        return not self.user_access_control.check_access_level_for_resource("query", "viewer")

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
