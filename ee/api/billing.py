import re
import json
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, NoReturn, Optional, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import models
from django.http import HttpResponse, StreamingHttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.cache import patch_vary_headers

import requests
import structlog
import posthoganalytics
from dateutil.relativedelta import relativedelta
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_serializer
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.fields import OptionalBooleanField
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import PARENT_LOOKUP_KWARG_PREFIX, TeamAndOrgViewSetMixin
from posthog.api.streaming import streaming_response
from posthog.api.utils import action
from posthog.cloud_utils import get_cached_instance_license
from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.llm.gateway_internal_client import AIGatewayInternalError, get_org_spend
from posthog.models import Organization, OrganizationIntegration, Team, User
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_provisioning import get_billing_lock_partner
from posthog.permissions import get_authenticator_scoped_team_ids, get_authenticator_scopes
from posthog.rate_limit import PersonalApiKeyOrUserRateThrottle
from posthog.user_permissions import UserPermissions
from posthog.utils import get_trusted_client_ip, relative_date_parse

from products.access_control.backend.facade.user_access_control import UserAccessControl, visible_teams_for_user

from ee.billing.billing_manager import (
    BillingManager,
    BillingServiceResponseError,
    http_session,
    raise_if_billing_managed_by_partner,
)
from ee.billing.billing_types import USAGE_TYPE_VALUES
from ee.billing.exports import (  # noqa: F401
    _EXPORT_STREAMS,
    _gzip_stream,
    _release_export_stream_slot,
    _released_after,
    _resolve_team_labels,
    _rewrite_csv_labels,
    _stream_chunks,
    _take_export_stream_slot,
    exportable_team_ids,
)
from ee.billing.grants import (
    BILLING_LIMIT_TODAYS_USAGE_KEYS,
    _billing_limit_todays_usage_enabled,
    _member_billing_usage_spend_read_access_enabled,
    _owner_only_billing_enabled,
)
from ee.models import License
from ee.settings import BILLING_SERVICE_URL

logger = structlog.get_logger(__name__)

BILLING_SERVICE_JWT_AUD = "posthog:license-key"


class BillingQueryTimeout(APIException):
    """The billing service did not answer a usage or spend query in time.

    A 400 rather than a 502 or 504, because the person can fix it by asking for less: fewer
    projects, a shorter range, or an export. The detail is shown to them, so it says what to
    change.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "usage_query_timeout"
    default_detail = (
        "This request took too long to complete. Select fewer projects, choose a shorter date "
        "range, or export the data instead."
    )


class BillingQueryTooLarge(APIException):
    """Billing refused a breakdown as more than it will hold for one request."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "usage_breakdown_too_large"
    default_detail = (
        "This breakdown is too large to load at once. Select fewer projects or products, choose a "
        "shorter date range or a coarser interval, or export the data instead."
    )


class BillingDateRangeTooLong(APIException):
    """Billing serves at most a year per request."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "usage_date_range_too_long"
    default_detail = "The date range is longer than a year. Choose a range of at most a year."


class BillingQueryRejected(APIException):
    """Billing refused the request for a reason the page has no guidance for."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "billing_query_rejected"
    default_detail = "Billing could not answer this request. Adjust the filters and try again."


class BillingServiceError(APIException):
    """Billing failed or answered in a shape the proxy does not recognise."""

    status_code = status.HTTP_502_BAD_GATEWAY
    default_code = "billing_service_error"
    default_detail = "Billing could not answer this request. Try again in a moment."


class PaymentAuthorizationRejected(APIException):
    """Billing refused to start the payment authorization."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "payment_authorization_rejected"
    default_detail = "We could not start the payment setup. Close this window and try again."


class BillingManagedByProviderError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "billing_managed_by_provider"
    default_detail = "Billing for this organization is managed outside PostHog. Contact support to change your plan."
    default_type = "invalid_request"


@contextmanager
def translate_managed_by_provider_refusal() -> Iterator[None]:
    try:
        yield
    except BillingServiceResponseError as error:
        body = error.body
        if (
            error.status_code != status.HTTP_400_BAD_REQUEST
            or not isinstance(body, dict)
            or body.get("code") != BillingManagedByProviderError.default_code
        ):
            raise
        message = body.get("error")
        raise BillingManagedByProviderError(message if isinstance(message, str) and message else None) from error


class BillingExportThrottle(PersonalApiKeyOrUserRateThrottle):
    """How often one person may start an export. Each one has billing build a whole file."""

    scope = "billing_export"
    rate = settings.BILLING_EXPORT_THROTTLE_RATE


# Billing's guidance codes on the usage and spend endpoints, each with the page's own sentence.
# Billing's own text is never returned to the browser: it is written for API callers, and an
# unexpected body could carry internal detail.
BILLING_GUIDANCE_ERRORS: dict[str, type[APIException]] = {
    BillingQueryTimeout.default_code: BillingQueryTimeout,
    BillingQueryTooLarge.default_code: BillingQueryTooLarge,
    BillingDateRangeTooLong.default_code: BillingDateRangeTooLong,
}

BILLING_VALIDATION_ERROR_MESSAGES = {
    "required": "This field is required.",
    "invalid_input": "Invalid value. Check this parameter's format and allowed values.",
    "invalid_choice": "Select a valid option for this parameter.",
}


BREAKDOWNS_MESSAGE = "Value must be a JSON array containing only 'type' and/or 'team'."
# Spend adds across products, so the spend read serves a project on its own. Usage counts each
# type in units that do not add: events, recordings, rows. So the usage read serves a project
# breakdown only beside the product one.
USAGE_BREAKDOWNS_MESSAGE = (
    'Pass [], ["type"] or ["type","team"]. To break usage down by project, pass "type" with '
    '"team": billing counts usage per product, and the counts do not add up across products.'
)


BILLING_ACCESS_DENIED_MESSAGE = (
    "Your PostHog user does not have billing access for this organization. "
    "Ask someone with billing access to run this or update your role."
)
BILLING_USAGE_SPEND_ACCESS_DENIED_MESSAGE = (
    "Your PostHog user does not have access to billing usage and spend for this organization. "
    "Ask someone with billing access to run this or update your role."
)
BILLING_PROJECT_ACCESS_DENIED_MESSAGE = (
    "The requested projects are not available to this PostHog user or token. "
    "Adjust the project filter or ask someone with billing access to run this."
)


def user_has_billing_access(user: User, organization: Organization) -> bool:
    membership = OrganizationMembership.objects.filter(user=user, organization=organization).only("level").first()
    if not membership:
        return False

    if membership.level >= OrganizationMembership.Level.OWNER:
        return True

    if membership.level < OrganizationMembership.Level.ADMIN:
        return False

    # Only a confirmed disabled flag lets admins through. Unknown flag state fails closed to owners.
    return _owner_only_billing_enabled(user, organization) is False


def _todays_usage_value(usage_key: str, usage: dict[str, Any]) -> int:
    value = usage.get("todays_usage")
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"Invalid today's usage value for {usage_key}.")
    if value < 0:
        raise ValidationError(f"Invalid today's usage value for {usage_key}.")
    return value


def _todays_usage_by_usage_key(organization: Organization) -> dict[str, int]:
    usage_summary = organization.usage or {}
    todays_usage_by_usage_key: dict[str, int] = {}

    for usage_key in BILLING_LIMIT_TODAYS_USAGE_KEYS:
        usage = usage_summary.get(usage_key)
        if usage is None:
            continue
        if not isinstance(usage, dict):
            raise ValidationError(f"Invalid current usage summary for {usage_key}.")

        todays_usage = _todays_usage_value(usage_key, usage)
        if todays_usage:
            todays_usage_by_usage_key[usage_key] = todays_usage

    return todays_usage_by_usage_key


def user_has_billing_usage_spend_read_access(user: User, organization: Organization) -> bool:
    membership = OrganizationMembership.objects.filter(user=user, organization=organization).only("level").first()
    if not membership:
        return False

    if membership.level >= OrganizationMembership.Level.OWNER:
        return True

    # Only a confirmed disabled flag lets non-owners through. Unknown flag state fails closed to owners.
    if _owner_only_billing_enabled(user, organization) is not False:
        return False

    if membership.level >= OrganizationMembership.Level.ADMIN:
        return True

    if membership.level < OrganizationMembership.Level.MEMBER:
        return False

    return _member_billing_usage_spend_read_access_enabled(user, organization)


def is_token_auth_request(request: Request) -> bool:
    return get_authenticator_scopes(getattr(request, "successful_authenticator", None)) is not None


class HasBillingAccess(permissions.BasePermission):
    """
    Permission to allow users with Billing access to access Billing endpoints.
    """

    message = BILLING_ACCESS_DENIED_MESSAGE

    def has_permission(self, request: Request, view: Any) -> bool:
        try:
            org = view._get_org_required()
        except Exception:
            return False

        if not isinstance(request.user, User):
            return False

        return user_has_billing_access(request.user, org)


class HasBillingUsageSpendReadAccess(permissions.BasePermission):
    """
    Permission for read-only billing usage/spend endpoints.
    """

    message = BILLING_USAGE_SPEND_ACCESS_DENIED_MESSAGE

    def has_permission(self, request: Request, view: Any) -> bool:
        try:
            org = view._get_org_required()
        except Exception:
            return False

        if not isinstance(request.user, User):
            return False

        return user_has_billing_usage_spend_read_access(request.user, org)


class BillingNotManagedByPartner(permissions.BasePermission):
    def has_permission(self, request: Request, view: Any) -> bool:
        organization = view._get_org()
        if organization is not None:
            raise_if_billing_managed_by_partner(organization)
        return True


def billing_managed_by_partner(organization: Organization | None) -> dict[str, str] | None:
    partner = get_billing_lock_partner(organization) if organization else None
    return {"partner_name": partner.name} if partner else None


def vercel_invoices_url(organization: Organization | None) -> str | None:
    if organization is None:
        return None
    vercel_integration = OrganizationIntegration.objects.filter(
        organization=organization,
        kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
    ).first()
    if not vercel_integration or not vercel_integration.integration_id:
        return None
    account_url = vercel_integration.config.get("account", {}).get("url", "")
    return f"{account_url}/invoices" if account_url else None


class BillingSerializer(serializers.Serializer):
    plan = serializers.CharField(max_length=100)
    billing_limit = serializers.IntegerField()


class BillingManagedByPartnerSerializer(serializers.Serializer):
    partner_name = serializers.CharField(
        allow_blank=True, help_text="Name of the partner that pays for this organization. Can be empty."
    )


BILLING_MANAGED_BY_PARTNER_HELP_TEXT = (
    "Set when a provisioning partner pays for this organization and the organization has no Stripe customer of "
    "its own. Self-serve subscription and payment changes are refused while it is set. Null otherwise."
)


@extend_schema_serializer(many=False)
class BillingOverviewResponseSerializer(serializers.Serializer):
    customer_id = serializers.CharField(required=False, allow_null=True)
    billing_plan = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    subscription_level = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    has_active_subscription = serializers.BooleanField(required=False)
    is_annual_plan_customer = serializers.BooleanField(required=False)
    free_trial_until = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    current_total_amount_usd = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    current_total_amount_usd_after_discount = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    projected_total_amount_usd = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    projected_total_amount_usd_after_discount = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    projected_total_amount_usd_with_limit = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    projected_total_amount_usd_with_limit_after_discount = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )
    discount_amount_usd = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    discount_percent = serializers.FloatField(required=False, allow_null=True)
    amount_off_expires_at = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    startup_program_label = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    startup_program_label_previous = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    stripe_portal_url = serializers.URLField(required=False, allow_blank=True, allow_null=True)
    external_billing_provider_invoices_url = serializers.URLField(required=False, allow_blank=True, allow_null=True)
    products = serializers.ListField(
        child=serializers.DictField(child=serializers.JSONField(allow_null=True)),
        required=False,
        help_text="Subscribed and available products/addons with pricing, plan, limit, usage, and entitlement metadata.",
    )
    available_product_features = serializers.ListField(child=serializers.CharField(), required=False)
    usage_summary = serializers.JSONField(required=False)
    billing_period = serializers.JSONField(required=False, allow_null=True)
    custom_limits_usd = serializers.JSONField(required=False)
    next_period_custom_limits_usd = serializers.JSONField(required=False)
    trial = serializers.JSONField(required=False, allow_null=True)
    license = serializers.JSONField(required=False, allow_null=True)
    account_owner = serializers.JSONField(required=False, allow_null=True)
    customer_trust_scores = serializers.JSONField(required=False)
    never_drop_data = serializers.BooleanField(required=False)
    billing_managed_by_partner = BillingManagedByPartnerSerializer(
        allow_null=True, help_text=BILLING_MANAGED_BY_PARTNER_HELP_TEXT
    )


class LicenseKeySerializer(serializers.Serializer):
    license = serializers.CharField()


class BillingUsageRequestSerializer(serializers.Serializer):
    """
    Serializer for the usage and spend requests to the billing service.
    Only responsible for parsing dates, passes through other params.
    """

    start_date = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text=(
            'Start date (YYYY-MM-DD, UTC), or "all" for 2020-01-01. If both dates are omitted, defaults to 30 days ago.'
        ),
    )
    end_date = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text=(
            "End date (YYYY-MM-DD, UTC), inclusive. Defaults to yesterday if both dates are omitted, "
            "or today if only start_date is provided."
        ),
    )
    usage_types = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text=(
            "JSON-encoded array of usage type identifiers to filter on. Valid values: "
            + ", ".join(USAGE_TYPE_VALUES)
            + '. E.g. ["event_count_in_period","recording_count_in_period"]. Omit for all types.'
        ),
    )
    team_ids = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text=(
            "JSON-encoded array of numeric team/project IDs to filter on, "
            "for example [1,2]. Omit for all projects available to the caller. Full billing-access callers can read "
            "all organization projects; member read-only callers are limited to visible projects and any project "
            "scope on their token."
        ),
    )
    breakdowns = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text=(
            'JSON-encoded array of breakdown dimensions. Valid values are "type" and "team", '
            'for example ["type","team"]. Omit for a single aggregate series.'
        ),
    )
    interval = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    top_projects = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=200,
        help_text=(
            "With a project breakdown, return only this many highest-usage projects and fold "
            "the rest into a single 'all other projects' series, so the totals still reconcile. "
            "Omit it to get every project."
        ),
    )
    page_size = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=1000,
        help_text=(
            "Return at most this many series, ranked by total, with a `next` cursor for the "
            "page after. A caller that pages never approaches the size this endpoint refuses "
            "oversized breakdowns at. Requires a project breakdown."
        ),
    )
    after = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=512,
        help_text="The `next` cursor from the previous page. Opaque. Ignored without page_size.",
    )

    def _parse_date(self, date_str: Optional[str], field_name: str) -> Optional[str]:
        """Shared date parsing logic into YYYY-MM-DD format. Handles relative dates too."""
        if not date_str:
            return None

        try:
            parsed_date = relative_date_parse(date_str, ZoneInfo("UTC"))
            return parsed_date.strftime("%Y-%m-%d")
        except Exception:
            raise serializers.ValidationError({field_name: f"Could not parse date '{date_str}'."})

    def validate_start_date(self, value: Optional[str]) -> Optional[str]:
        """Validate and normalize the start_date, handling 'all'."""
        if value == "all":
            return "2020-01-01"
        return self._parse_date(value, "start_date")

    def validate_end_date(self, value: Optional[str]) -> Optional[str]:
        """Validate and normalize the end_date."""
        return self._parse_date(value, "end_date")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        today_utc = timezone.now().astimezone(ZoneInfo("UTC")).date()
        if not attrs.get("start_date") and not attrs.get("end_date"):
            attrs["start_date"] = (today_utc - timedelta(days=30)).isoformat()
            attrs["end_date"] = (today_utc - timedelta(days=1)).isoformat()
        elif attrs.get("start_date") and not attrs.get("end_date"):
            attrs["end_date"] = today_utc.isoformat()
        return attrs

    def validate_usage_types(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return value

        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            raise serializers.ValidationError("Value must be a JSON array of usage type identifiers.")

        if not isinstance(parsed, list) or any(not isinstance(usage_type, str) for usage_type in parsed):
            raise serializers.ValidationError("Value must be a JSON array of usage type identifiers.")

        return value

    def validate_team_ids(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return value

        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            raise serializers.ValidationError("Value must be a JSON array of numeric team IDs.")

        if not isinstance(parsed, list) or any(
            not isinstance(team_id, int) or isinstance(team_id, bool) for team_id in parsed
        ):
            raise serializers.ValidationError("Value must be a JSON array of numeric team IDs.")

        return value

    def validate_breakdowns(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return value

        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            raise serializers.ValidationError(BREAKDOWNS_MESSAGE)

        if not isinstance(parsed, list) or any(breakdown not in ("type", "team") for breakdown in parsed):
            raise serializers.ValidationError(BREAKDOWNS_MESSAGE)

        return value


class BillingTimeSeriesPointSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    label = serializers.CharField(required=False, allow_blank=True)  # type: ignore[assignment]
    data = serializers.ListField(child=serializers.FloatField(), required=False)  # type: ignore[assignment]
    dates = serializers.ListField(child=serializers.CharField(), required=False)
    breakdown_type = serializers.ChoiceField(choices=["type", "team", "multiple"], allow_null=True, required=False)
    breakdown_value = serializers.JSONField(allow_null=True, required=False)


class BillingTimeSeriesResponseSerializer(serializers.Serializer):
    status = serializers.CharField(required=False)
    type = serializers.CharField(required=False)
    customer_id = serializers.IntegerField(required=False)
    results = BillingTimeSeriesPointSerializer(many=True)
    team_id_options = serializers.ListField(child=serializers.IntegerField(), required=False)
    next = serializers.CharField(required=False, allow_blank=True)
    total_count = serializers.IntegerField(required=False)


class BillingTeamOptionsResponseSerializer(serializers.Serializer):
    team_id_options = serializers.ListField(
        child=serializers.IntegerField(), help_text="Project ids that appear in the organization's usage reports."
    )


class BillingPeriodResponseSerializer(serializers.Serializer):
    current_period_start = serializers.DateTimeField(
        allow_null=True,
        help_text="Start of the organization's current billing period, or null when billing has not synced a period.",
    )
    current_period_end = serializers.DateTimeField(
        allow_null=True,
        help_text="End of the organization's current billing period, or null when billing has not synced a period.",
    )


class BillingPaymentOrganizationSerializer(serializers.Serializer):
    organization_id = serializers.UUIDField(help_text="Organization selected when this payment flow started.")

    def validate_organization_id(self, value: UUID) -> UUID:
        if not isinstance(self.initial_data.get("organization_id"), str):
            raise serializers.ValidationError("A UUID string is required.")
        return value


class BillingOverviewRequestSerializer(serializers.Serializer):
    organization_id = serializers.UUIDField(required=False, help_text="Explicit organization to refresh after payment.")
    include_forecasting = OptionalBooleanField(required=False, help_text="Whether to include usage forecasting.")


class BillingActivationRequestSerializer(BillingPaymentOrganizationSerializer):
    products = serializers.CharField(required=False, help_text="Product and plan keys to activate.")
    intent_product = serializers.CharField(required=False, help_text="Product that prompted the subscription upgrade.")
    custom_limits_usd = serializers.CharField(
        required=False, allow_blank=True, help_text="JSON-encoded custom product limits to apply on activation."
    )


class BillingActivationResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(required=False, help_text="Whether the subscription was activated.")
    must_setup_payment = serializers.BooleanField(required=False, help_text="Whether payment details are required.")
    products = serializers.ListField(
        child=serializers.CharField(), required=False, help_text="Products activated by this request."
    )
    error = serializers.CharField(required=False, allow_null=True, help_text="Reason activation failed.")


class BillingAuthorizationResponseSerializer(serializers.Serializer):
    clientSecret = serializers.CharField(required=False, help_text="Stripe client secret for the authorization intent.")
    success = serializers.BooleanField(
        required=False, help_text="Whether authorization completed without a payment form."
    )


class BillingAuthorizationStatusRequestSerializer(BillingPaymentOrganizationSerializer):
    payment_intent_id = serializers.CharField(
        required=False, allow_null=True, help_text="Stripe payment intent created for this organization."
    )


class BillingAuthorizationStatusResponseSerializer(serializers.Serializer):
    status = serializers.CharField(required=False, help_text="Authorization status: loading, success, or failed.")
    error = serializers.CharField(required=False, allow_null=True, help_text="Reason authorization failed.")
    success = serializers.BooleanField(
        required=False, help_text="Whether authorization completed without a payment form."
    )


# Billing charges between these amounts for AI credit, and refuses anything else.
MINIMUM_AI_CREDIT_USD = Decimal("20.00")
MAXIMUM_AI_CREDIT_USD = Decimal("1000000.00")


class AICreditsUnavailable(APIException):
    """Billing doesn't sell AI credits to the organization: it isn't in the rollout, or a partner bills it."""

    status_code = status.HTTP_403_FORBIDDEN
    default_code = "ai_credits_unavailable"
    default_detail = "AI credits aren't available for this organization."


class AICreditsNoCard(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "ai_credits_no_card"
    default_detail = "Add a card to your billing details, then try again."


class AICreditsTaxUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "ai_credits_tax_unavailable"
    default_detail = "We can't work out the tax right now. Try again in a minute."


class AICreditsCardDeclined(APIException):
    status_code = status.HTTP_402_PAYMENT_REQUIRED
    default_code = "ai_credits_card_declined"
    default_detail = "Your bank declined the card. Update your card, then try again."


class AICreditsTotalChanged(APIException):
    """The tax changed after the quote, so billing charged nothing. The page quotes again."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "ai_credits_total_changed"
    default_detail = "The tax on this purchase changed. Check the new total, then pay again."


class AICreditsPurchaseEnded(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "ai_credits_purchase_ended"
    default_detail = "This purchase ended without a charge. Start a new one."


class AICreditsPurchaseUnfinished(APIException):
    """Billing didn't answer the purchase. A retry with the same idempotency key charges at most once."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "ai_credits_purchase_unfinished"
    default_detail = "The purchase didn't finish. Try again. You won't be charged twice."


class AICreditsSettingsRejected(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "ai_credits_settings_rejected"
    default_detail = "We couldn't save these settings. Check the amounts and the card on file, then try again."


class AIReloadDisabledReason(models.TextChoices):
    CARD_DECLINED = "card_declined", "Card declined"
    AUTHENTICATION_REQUIRED = "authentication_required", "Card needs authentication"
    NO_CARD = "no_card", "No card on file"


class AICreditPurchaseStatus(models.TextChoices):
    PAID = "paid", "Paid"
    REQUIRES_ACTION = "requires_action", "Requires action"


class AICreditHistoryKind(models.TextChoices):
    PURCHASE = "purchase", "Purchase"
    AUTOMATIC_RELOAD = "automatic_reload", "Automatic reload"


class AICreditHistoryStatus(models.TextChoices):
    ADDED = "added", "Added"
    PENDING = "pending", "Pending"


def _usd_field(help_text: str, **kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=12, decimal_places=2, help_text=help_text, **kwargs)


class AIAutomaticReloadSettingsSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(help_text="Whether automatic reload is on.")
    target_usd = _usd_field("The AI balance in USD that a reload brings the organization up to.", allow_null=True)
    monthly_reload_limit_usd = _usd_field(
        "The most that automatic reloads charge in a billing period, in USD. Null means no limit.", allow_null=True
    )
    disabled_reason = serializers.ChoiceField(
        choices=AIReloadDisabledReason.choices,
        allow_null=True,
        help_text="Why billing turned automatic reload off after a failed reload. Null otherwise.",
    )
    disabled_at = serializers.DateTimeField(
        allow_null=True, help_text="When billing turned automatic reload off after a failed reload."
    )


class AICreditSettingsResponseSerializer(serializers.Serializer):
    monthly_spend_limit_usd = _usd_field(
        "The most the organization can spend on AI in a billing period, in USD. Null means no limit.",
        allow_null=True,
    )
    low_balance_threshold_usd = _usd_field(
        "Automatic reload charges the card when the AI balance drops below this many USD.", allow_null=True
    )
    automatic_reload = AIAutomaticReloadSettingsSerializer(help_text="The automatic reload settings.")


class AISpendLimitRequestSerializer(serializers.Serializer):
    monthly_spend_limit_usd = _usd_field(
        'The most the organization can spend on AI in a billing period, in USD, such as "250.00". '
        "Pass null to remove the limit.",
        min_value=Decimal("0"),
        max_value=MAXIMUM_AI_CREDIT_USD,
        allow_null=True,
    )


class AIAutomaticReloadRequestSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False, help_text="Turn automatic reload on or off.")
    low_balance_threshold_usd = _usd_field(
        'Reload when the AI balance drops below this many USD, such as "20.00".',
        min_value=Decimal("0"),
        max_value=MAXIMUM_AI_CREDIT_USD,
        allow_null=True,
        required=False,
    )
    target_usd = _usd_field(
        f"The AI balance in USD that a reload brings the organization up to. "
        f"At least ${MINIMUM_AI_CREDIT_USD} more than the low-balance amount.",
        min_value=MINIMUM_AI_CREDIT_USD,
        max_value=MAXIMUM_AI_CREDIT_USD,
        allow_null=True,
        required=False,
    )
    monthly_reload_limit_usd = _usd_field(
        f"The most that automatic reloads charge in a billing period, in USD. "
        f"At least ${MINIMUM_AI_CREDIT_USD}. Pass null for no limit.",
        min_value=MINIMUM_AI_CREDIT_USD,
        max_value=MAXIMUM_AI_CREDIT_USD,
        allow_null=True,
        required=False,
    )
    consent_text = serializers.CharField(
        required=False,
        max_length=2000,
        help_text="The exact words the person agreed to. Turning automatic reload on needs them.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("enabled") is True and not attrs.get("consent_text"):
            raise ValidationError({"consent_text": "Agree to the automatic charges to turn automatic reload on."})
        threshold, target = attrs.get("low_balance_threshold_usd"), attrs.get("target_usd")
        if threshold is not None and target is not None and target - threshold < MINIMUM_AI_CREDIT_USD:
            raise ValidationError(
                {"target_usd": f"Reload to at least ${MINIMUM_AI_CREDIT_USD} more than the low-balance amount."}
            )
        return attrs


class AICreditHistoryRequestSerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        min_value=1, max_value=100, default=50, help_text="How many entries to return, from 1 to 100."
    )
    offset = serializers.IntegerField(min_value=0, default=0, help_text="How many of the newest entries to skip.")


class AICreditHistoryEntrySerializer(serializers.Serializer):
    created_at = serializers.DateTimeField(help_text="When the purchase or reload was made.")
    kind = serializers.ChoiceField(
        choices=AICreditHistoryKind.choices, help_text="A purchase by a person, or an automatic reload."
    )
    amount_usd = _usd_field("The AI credit bought, in USD.")
    tax_usd = _usd_field("The tax charged on it, in USD.")
    total_usd = _usd_field("The amount charged to the card, in USD.")
    status = serializers.ChoiceField(
        choices=AICreditHistoryStatus.choices,
        help_text="Pending until the credit reaches the organization's AI balance.",
    )
    receipt_url = serializers.URLField(allow_null=True, help_text="Stripe's receipt for the payment.")


class AICreditHistoryResponseSerializer(serializers.Serializer):
    results = AICreditHistoryEntrySerializer(many=True, help_text="Purchases and automatic reloads, newest first.")
    has_more = serializers.BooleanField(help_text="Whether older entries follow.")


class AICreditCardSerializer(serializers.Serializer):
    brand = serializers.CharField(help_text='The card brand, such as "visa".')
    last4 = serializers.CharField(help_text="The last four digits of the card number.")
    exp_month = serializers.IntegerField(help_text="The month the card expires.")
    exp_year = serializers.IntegerField(help_text="The year the card expires.")


class AICreditCardResponseSerializer(serializers.Serializer):
    card = AICreditCardSerializer(allow_null=True, help_text="The card that pays for AI credits. Null when none.")


class AICreditQuoteRequestSerializer(serializers.Serializer):
    amount_usd = _usd_field(
        f'The AI credit to buy, in USD, such as "50.00". '
        f"At least ${MINIMUM_AI_CREDIT_USD} and at most ${MAXIMUM_AI_CREDIT_USD:,}.",
        min_value=MINIMUM_AI_CREDIT_USD,
        max_value=MAXIMUM_AI_CREDIT_USD,
    )


class AICreditQuoteResponseSerializer(serializers.Serializer):
    amount_usd = _usd_field("The AI credit to buy, in USD.")
    tax_usd = _usd_field("The tax on it, in USD.")
    total_usd = _usd_field("What the card is charged, in USD.")


class AICreditPurchaseRequestSerializer(AICreditQuoteRequestSerializer):
    total_usd = _usd_field(
        "The total the person confirmed, tax included, from the quote. "
        "When the tax has changed since, nothing is charged.",
        min_value=Decimal("0"),
    )
    idempotency_key = serializers.CharField(
        max_length=100,
        help_text="A new value, such as a UUID, for each purchase the person confirms. "
        "Send the same value again to retry that purchase.",
    )


class AICreditPurchaseResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=AICreditPurchaseStatus.choices,
        help_text="Paid, or waiting for the person to authenticate the payment with their bank.",
    )
    total_usd = _usd_field("What the card is charged, in USD.")
    client_secret = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Confirm this with Stripe.js when the status is requires_action.",
    )


class AISpendUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "ai_spend_unavailable"
    default_detail = "AI spend isn't available right now. Try again in a few minutes."


class AISpendPeriod(models.TextChoices):
    CURRENT = "current", "Current"
    PREVIOUS = "previous", "Previous"


def _spend_field(help_text: str) -> serializers.DecimalField:
    # The gateway's ledger keeps amounts to the millionth of a dollar.
    return serializers.DecimalField(max_digits=18, decimal_places=6, help_text=help_text)


class AISpendRequestSerializer(serializers.Serializer):
    period = serializers.ChoiceField(
        choices=AISpendPeriod.choices,
        default=AISpendPeriod.CURRENT,
        help_text="The current billing period, or the one before it.",
    )


class AISpendProductSerializer(serializers.Serializer):
    product = serializers.CharField(help_text="The AI product, as the AI gateway names it.")
    name = serializers.CharField(help_text="The product's name for display.")
    spend_usd = _spend_field("Charged to the AI balance in the period, in USD.")
    free_usd = _spend_field("The list cost minus the charged amount, in USD.")


class AISpendDaySerializer(serializers.Serializer):
    date = serializers.DateField(help_text="The day, in UTC.")
    spend_usd = serializers.DictField(
        child=_spend_field("Charged that day, in USD."),
        help_text="Charged to the AI balance that day, in USD, by product.",
    )


class AISpendResponseSerializer(serializers.Serializer):
    balance_usd = _spend_field("The organization's AI balance now, in USD. Below zero after overage.")
    period_start = serializers.DateField(help_text="The first day of the billing period.")
    period_end = serializers.DateField(help_text="The day the next billing period starts.")
    spend_usd = _spend_field("Charged to the AI balance in the period, in USD.")
    free_usd = _spend_field("The list cost minus the charged amount, in USD.")
    products = AISpendProductSerializer(many=True, help_text="Spend by AI product.")
    days = AISpendDaySerializer(many=True, help_text="Spend by day, for the days so far.")


def ai_spend_period(organization: Organization, period: str, now: datetime) -> tuple[date, date]:
    """The period's first day and the next period's first day. An organization with no billing period gets the calendar month."""
    billing_period = organization.current_billing_period
    if billing_period:
        start, end = billing_period.start.date(), billing_period.end.date()
    else:
        start = now.date().replace(day=1)
        end = start + relativedelta(months=1)
    if period == AISpendPeriod.PREVIOUS:
        return start - relativedelta(months=1), start
    return start, end


def _ai_credits_error(
    error: BillingServiceResponseError,
    organization: Organization,
    bad_request: type[APIException],
    unavailable: type[APIException],
) -> APIException:
    """The named error for billing's answer to an AI credits call. Billing's own words never reach the page."""
    logger.warning("ai_credits_billing_error", organization_id=str(organization.id), status=error.status_code)
    body = error.body if isinstance(error.body, dict) else {}
    if error.status_code == status.HTTP_400_BAD_REQUEST:
        return bad_request()
    if error.status_code == status.HTTP_402_PAYMENT_REQUIRED:
        return AICreditsCardDeclined()
    if error.status_code == status.HTTP_403_FORBIDDEN:
        return AICreditsUnavailable()
    if error.status_code == status.HTTP_409_CONFLICT:
        return AICreditsTotalChanged() if body.get("status") == "total_changed" else AICreditsPurchaseEnded()
    if error.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
        return unavailable()
    return BillingServiceError()


@extend_schema(tags=["billing"])
class BillingViewset(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = BillingSerializer
    pagination_class = None
    param_derived_from_user_current_team: Literal["team_id", "project_id"] | None = "team_id"

    scope_object = "billing"
    scope_object_read_actions = ["list", "usage", "spend", "usage_export", "spend_export", "usage_team_options"]
    scope_object_write_actions: list[str] = []
    # OpenAPI skips root-router viewsets that derive their team from the current user.
    # Billing opts in so generated clients and MCP scaffolding include these read actions.
    force_include_in_api_docs = True

    payment_actions = {"activate", "authorize", "authorize_status"}

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        scoped_billing_read = self.action == "list" and "organization_id" in request.query_params
        if self.action in self.payment_actions or scoped_billing_read:
            serializer = BillingPaymentOrganizationSerializer(
                data=request.query_params if scoped_billing_read else request.data
            )
            serializer.is_valid(raise_exception=True)
            # Configure normal organization scope before shared permissions resolve any cached
            # routing properties. The user's current project can change in another browser tab.
            self.param_derived_from_user_current_team = None
            self.kwargs[f"{PARENT_LOOKUP_KWARG_PREFIX}organization_id"] = str(
                serializer.validated_data["organization_id"]
            )
        super().initial(request, *args, **kwargs)

    def get_billing_manager(self) -> BillingManager:
        license = get_cached_instance_license()
        user = self.request.user if isinstance(self.request.user, User) and self.request.user.distinct_id else None
        return BillingManager(license, user, ip_address=get_trusted_client_ip(self.request))

    @validated_request(
        query_serializer=BillingOverviewRequestSerializer,
        responses={200: OpenApiResponse(response=BillingOverviewResponseSerializer)},
    )
    def list(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        license = get_cached_instance_license()
        if license and not license.is_v2_license:
            raise NotFound("Billing is not supported for this license type")

        org = self._get_org()
        if is_token_auth_request(request):
            if not org or not isinstance(request.user, User) or not user_has_billing_access(request.user, org):
                raise PermissionDenied(BILLING_ACCESS_DENIED_MESSAGE)

        # If on Cloud and we have the property billing - return 404 as we always use legacy billing it it exists
        if hasattr(org, "billing"):
            if org.billing.stripe_subscription_id:  # type: ignore
                raise NotFound("Billing V1 is active for this organization")

        billing_manager = self.get_billing_manager()
        query = {}
        include_forecasting = request.validated_query_data.get("include_forecasting")
        if include_forecasting is not None:
            query["include_forecasting"] = str(include_forecasting).lower()
        response = billing_manager.get_billing(org, query)

        invoices_url = vercel_invoices_url(org)
        if invoices_url:
            response["external_billing_provider_invoices_url"] = invoices_url

        response["billing_managed_by_partner"] = billing_managed_by_partner(org)

        return Response(response)

    @extend_schema(
        summary="Get the current organization billing period",
        responses={200: BillingPeriodResponseSerializer},
    )
    @action(
        methods=["GET"],
        detail=False,
        url_path="period",
        permission_classes=[permissions.IsAuthenticated],
        required_scopes=["llm_gateway:read"],
    )
    def period(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        billing_period = self._get_org_required().current_billing_period
        return Response(
            BillingPeriodResponseSerializer(
                {
                    "current_period_start": billing_period.start if billing_period else None,
                    "current_period_end": billing_period.end if billing_period else None,
                }
            ).data
        )

    @extend_schema(exclude=True)
    @action(
        methods=["PATCH"],
        detail=False,
        url_path="/",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess],
    )
    def patch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        distinct_id = None if self.request.user.is_anonymous else self.request.user.distinct_id
        license = get_cached_instance_license()
        if not license:
            raise Exception("There is no license configured for this instance yet.")

        org = self._get_org_required()
        if license and org:  # for mypy
            custom_limits_usd = request.data.get("custom_limits_usd")
            reset_limit_next_period = request.data.get("reset_limit_next_period")

            if custom_limits_usd or reset_limit_next_period:
                body = {}
                if custom_limits_usd:
                    body["custom_limits_usd"] = custom_limits_usd
                    if _billing_limit_todays_usage_enabled(cast(User, self.request.user), org):
                        todays_usage = _todays_usage_by_usage_key(org)
                        if todays_usage:
                            body["todays_usage_by_usage_key"] = todays_usage
                if reset_limit_next_period:
                    body["reset_limit_next_period"] = reset_limit_next_period

                billing_manager = self.get_billing_manager()
                billing_manager.update_billing(org, body)

                if custom_limits_usd and distinct_id:
                    posthoganalytics.capture(
                        "billing limits updated",
                        distinct_id=distinct_id,
                        properties={**custom_limits_usd},
                        groups=(
                            groups(org, self.request.user.team) if hasattr(self.request.user, "team") else groups(org)
                        ),
                    )
                    posthoganalytics.group_identify(
                        "organization",
                        str(org.id),
                        properties={f"billing_limits_{key}": value for key, value in custom_limits_usd.items()},
                    )

                if reset_limit_next_period and distinct_id:
                    posthoganalytics.capture(
                        "billing limits reset",
                        distinct_id=distinct_id,
                        properties={"reset_limit_next_period": reset_limit_next_period},
                    )
                    posthoganalytics.group_identify(
                        "organization",
                        str(org.id),
                        properties={"reset_limit_next_period": reset_limit_next_period},
                    )

        return self.list(request, *args, **kwargs)

    @extend_schema(request=BillingActivationRequestSerializer, responses={200: BillingActivationResponseSerializer})
    @action(
        methods=["POST"],
        detail=False,
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess, BillingNotManagedByPartner],
    )
    def activate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        organization = self._get_org_required()
        billing_manager = self.get_billing_manager()
        serializer = BillingActivationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = {key: value for key, value in serializer.validated_data.items() if key != "organization_id"}
        with translate_managed_by_provider_refusal():
            res = billing_manager.activate_subscription(organization, data)
        return Response(res, status=status.HTTP_200_OK)

    class DeactivateSerializer(serializers.Serializer):
        products = serializers.CharField()

    @action(
        methods=["POST"],
        detail=False,
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess],
    )
    def deactivate(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        organization = self._get_org_required()

        serializer = self.DeactivateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        products = serializer.validated_data.get("products")

        try:
            billing_manager = self.get_billing_manager()
            billing_manager.deactivate_products(organization, products)
        except Exception as e:
            if len(e.args) > 2:
                detail_object = e.args[2]
                return Response(
                    {
                        "statusText": e.args[0],
                        "detail": detail_object.get("error_message", detail_object),
                        "link": detail_object.get("link", None),
                        "code": detail_object.get("code"),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            else:
                raise

        return self.list(request, *args, **kwargs)

    # nosemgrep: api-path-underscore -- shipped public API path, a rename breaks clients
    @action(
        methods=["POST"],
        detail=False,
        url_path="subscription/switch-plan",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess, BillingNotManagedByPartner],
    )
    def subscription_switch_plan(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        organization = self._get_org_required()
        billing_manager = self.get_billing_manager()
        res = billing_manager.switch_plan(organization, request.data)
        return Response(res, status=status.HTTP_200_OK)

    @action(
        methods=["GET"],
        detail=False,
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess, BillingNotManagedByPartner],
    )
    def portal(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = get_cached_instance_license()
        if not license:
            return Response(
                {"success": True},
                status=status.HTTP_200_OK,
            )

        organization = self._get_org_required()

        billing_manager = self.get_billing_manager()
        try:
            with translate_managed_by_provider_refusal():
                res = billing_manager._get_stripe_portal_url(organization)
        except BillingManagedByProviderError:
            invoices_url = vercel_invoices_url(organization)
            if invoices_url is None:
                raise
            return redirect(invoices_url)
        return redirect(res)

    @action(methods=["GET"], detail=False)
    def get_invoices(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = get_cached_instance_license()
        if not license:
            return Response(
                {"success": True},
                status=status.HTTP_200_OK,
            )

        organization = self._get_org_required()

        invoice_status = request.GET.get("status")

        try:
            billing_manager = self.get_billing_manager()
            res = billing_manager.get_invoices(organization, status=invoice_status)
        except Exception as e:
            if len(e.args) > 2:
                detail_object = e.args[2]
                if not isinstance(detail_object, dict):
                    raise
                # Billing puts its message under `detail`. The page shows it as guidance only when `detail`
                # is a string, so the message is passed through flat rather than as the whole body.
                detail = detail_object.get("error_message") or detail_object.get("detail") or detail_object
                return Response(
                    {"statusText": e.args[0], "detail": detail, "code": detail_object.get("code")},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            else:
                raise

        return Response(
            {
                "link": res.get("portal_url"),
                "count": res.get("count"),
            },
            status=status.HTTP_200_OK,
        )

    @action(methods=["GET"], detail=False, url_path="credits/overview")
    def credits_overview(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = get_cached_instance_license()
        if not license:
            return Response(
                {"success": True},
                status=status.HTTP_200_OK,
            )

        organization = self._get_org_required()

        billing_manager = self.get_billing_manager()
        res = billing_manager.credits_overview(organization)
        return Response(res, status=status.HTTP_200_OK)

    @action(
        methods=["POST"],
        detail=False,
        url_path="credits/purchase",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess, BillingNotManagedByPartner],
    )
    def purchase_credits(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = get_cached_instance_license()
        if not license:
            return Response(
                {"success": True},
                status=status.HTTP_200_OK,
            )

        organization = self._get_org_required()

        billing_manager = self.get_billing_manager()
        res = billing_manager.purchase_credits(organization, request.data)
        return Response(res, status=status.HTTP_200_OK)

    @action(
        methods=["POST"],
        detail=False,
        url_path="trials/activate",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess, BillingNotManagedByPartner],
    )
    def activate_trial(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        organization = self._get_org_required()
        billing_manager = self.get_billing_manager()
        res = billing_manager.activate_trial(organization, request.data)
        return Response(res, status=status.HTTP_200_OK)

    @action(
        methods=["POST"],
        detail=False,
        url_path="trials/cancel",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess],
    )
    def cancel_trial(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        organization = self._get_org_required()
        billing_manager = self.get_billing_manager()
        res = billing_manager.cancel_trial(organization, request.data)
        return Response(res, status=status.HTTP_200_OK)

    @extend_schema(
        request=BillingPaymentOrganizationSerializer, responses={200: BillingAuthorizationResponseSerializer}
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="activate/authorize",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess, BillingNotManagedByPartner],
    )
    def authorize(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = get_cached_instance_license()
        if not license:
            return Response(
                {"success": True},
                status=status.HTTP_200_OK,
            )

        organization = self._get_org_required()
        billing_manager = self.get_billing_manager()
        try:
            with translate_managed_by_provider_refusal():
                res = billing_manager.authorize(organization)
        except BillingServiceResponseError as e:
            # The billing body can hold database error text, so the caller gets a controlled message.
            logger.warning(
                "billing_authorize_error",
                organization_id=str(organization.id),
                upstream_status=e.status_code,
                body=str(e.body)[:500],
            )
            if 400 <= e.status_code < 500:
                raise PaymentAuthorizationRejected() from e
            raise BillingServiceError() from e
        return Response(res, status=status.HTTP_200_OK)

    @extend_schema(
        request=BillingAuthorizationStatusRequestSerializer,
        responses={200: BillingAuthorizationStatusResponseSerializer},
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="activate/authorize/status",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess],
    )
    def authorize_status(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = get_cached_instance_license()
        if not license:
            return Response(
                {"success": True},
                status=status.HTTP_200_OK,
            )

        organization = self._get_org_required()
        billing_manager = self.get_billing_manager()
        serializer = BillingAuthorizationStatusRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = {key: value for key, value in serializer.validated_data.items() if key != "organization_id"}
        res = billing_manager.authorize_status(organization, data)
        return Response(res, status=status.HTTP_200_OK)

    @action(
        methods=["PATCH"],
        detail=False,
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess],
    )
    def license(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = get_cached_instance_license()

        if license:
            raise PermissionDenied(
                "A valid license key already exists. This must be removed before a new one can be added."
            )

        organization = self._get_org_required()

        serializer = LicenseKeySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        license = License(key=serializer.validated_data["license"])
        ip_address = get_trusted_client_ip(request)
        res = http_session.get(
            f"{BILLING_SERVICE_URL}/api/billing",
            headers=BillingManager(license, ip_address=ip_address).get_auth_headers(organization),
        )

        if res.status_code != 200:
            raise ValidationError(
                {
                    "license": f"License could not be activated. Please contact support. (BillingService status {res.status_code})",
                }
            )
        data = res.json()
        BillingManager(license, ip_address=ip_address).update_license_details(data)
        return Response({"success": True})

    @action(
        methods=["POST"],
        detail=False,
        url_path="startups/apply",
        permission_classes=[permissions.IsAuthenticated],
    )
    def apply_startup_program(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        user = self.request.user
        if not isinstance(user, User):
            raise PermissionDenied("You must be logged in to apply for the startup program")

        organization_id = request.data.get("organization_id")
        if not organization_id:
            raise ValidationError({"organization_id": "This field is required."})

        organization = Organization.objects.get(id=organization_id)
        if not organization:
            raise ValidationError({"organization_id": "Organization not found."})

        if not user_has_billing_access(user, organization):
            raise PermissionDenied("You need Billing access to apply for the startup program")

        billing_manager = self.get_billing_manager()

        # Add user info to the request
        data = {
            **request.data,
            "email": user.email,
        }

        # "-" as fallback as they're required by some of the Zaps, e.g. Brilliant (merch)
        data["first_name"] = user.first_name if user.first_name else "-"
        data["last_name"] = user.last_name if user.last_name else "-"

        try:
            res = billing_manager.apply_startup_program(organization, data)
            return Response(res, status=status.HTTP_200_OK)
        except Exception as e:
            if len(e.args) > 2:
                detail_object = e.args[2]
                if not isinstance(detail_object, dict):
                    raise
                # Billing puts its message under `detail`. The page shows it as guidance only when `detail`
                # is a string, so the message is passed through flat rather than as the whole body.
                detail = detail_object.get("error_message") or detail_object.get("detail") or detail_object
                return Response(
                    {"statusText": e.args[0], "detail": detail, "code": detail_object.get("code")},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            else:
                raise

    @action(
        methods=["POST"],
        detail=False,
        url_path="coupons/claim",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess],
    )
    def claim_coupon(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        organization = self._get_org_required()

        code = request.data.get("code")
        if not code:
            raise ValidationError({"code": "This field is required."})

        billing_manager = self.get_billing_manager()

        try:
            res = billing_manager.claim_coupon(organization, {"code": code})
            return Response(res, status=status.HTTP_200_OK)
        except Exception as e:
            if len(e.args) > 2:
                detail_object = e.args[2]
                if not isinstance(detail_object, dict):
                    raise
                return Response(
                    {
                        "statusText": e.args[0],
                        "detail": detail_object.get("error_message") or detail_object.get("detail") or detail_object,
                        "code": detail_object.get("code"),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            else:
                raise

    @action(methods=["GET"], detail=False, url_path="coupons/overview")
    def coupons_overview(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = get_cached_instance_license()
        if not license:
            return Response({"claimed_coupons": []}, status=status.HTTP_200_OK)

        organization = self._get_org_required()
        billing_manager = self.get_billing_manager()
        res = billing_manager.coupons_overview(organization)
        return Response(res, status=status.HTTP_200_OK)

    def _ai_credits(
        self,
        call: Callable[[BillingManager, Organization], dict[str, Any]],
        *,
        bad_request: type[APIException] = AICreditsSettingsRejected,
        unavailable: type[APIException] = BillingServiceError,
    ) -> dict[str, Any]:
        if not get_cached_instance_license():
            raise NotFound("AI credits need PostHog Cloud.")
        organization = self._get_org_required()
        try:
            return call(self.get_billing_manager(), organization)
        except BillingServiceResponseError as error:
            raise _ai_credits_error(error, organization, bad_request, unavailable) from error
        except requests.RequestException as error:
            logger.warning("ai_credits_billing_unreachable", organization_id=str(organization.id))
            raise unavailable() from error

    @validated_request(responses={200: OpenApiResponse(response=AICreditSettingsResponseSerializer)})
    @action(
        methods=["GET"],
        detail=False,
        url_path="ai_credits/settings",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess],
    )
    def ai_credit_settings(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        answer = self._ai_credits(lambda manager, organization: manager.ai_credit_settings(organization))
        return Response(AICreditSettingsResponseSerializer(answer).data)

    @validated_request(
        request_serializer=AISpendLimitRequestSerializer,
        responses={200: OpenApiResponse(response=AICreditSettingsResponseSerializer)},
    )
    @action(
        methods=["PATCH"],
        detail=False,
        url_path="ai_credits/settings/spend_limit",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess, BillingNotManagedByPartner],
    )
    def ai_spend_limit(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        limit = request.validated_data["monthly_spend_limit_usd"]
        answer = self._ai_credits(
            lambda manager, organization: manager.update_ai_spend_limit(
                organization, {"monthly_spend_limit_usd": None if limit is None else str(limit)}
            )
        )
        return Response(AICreditSettingsResponseSerializer(answer).data)

    @validated_request(
        request_serializer=AIAutomaticReloadRequestSerializer,
        responses={200: OpenApiResponse(response=AICreditSettingsResponseSerializer)},
    )
    @action(
        methods=["PATCH"],
        detail=False,
        url_path="ai_credits/settings/automatic_reload",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess, BillingNotManagedByPartner],
    )
    def ai_automatic_reload(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        changes = {
            field: str(value) if isinstance(value, Decimal) else value
            for field, value in request.validated_data.items()
        }
        answer = self._ai_credits(
            lambda manager, organization: manager.update_ai_automatic_reload(organization, changes)
        )
        return Response(AICreditSettingsResponseSerializer(answer).data)

    @validated_request(
        query_serializer=AICreditHistoryRequestSerializer,
        responses={200: OpenApiResponse(response=AICreditHistoryResponseSerializer)},
    )
    @action(
        methods=["GET"],
        detail=False,
        url_path="ai_credits/history",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess],
    )
    def ai_credit_history(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        query = request.validated_query_data
        answer = self._ai_credits(
            lambda manager, organization: manager.ai_credit_history(organization, query["limit"], query["offset"])
        )
        return Response(AICreditHistoryResponseSerializer(answer).data)

    @validated_request(
        query_serializer=AISpendRequestSerializer,
        responses={200: OpenApiResponse(response=AISpendResponseSerializer)},
    )
    @action(
        methods=["GET"],
        detail=False,
        url_path="ai_credits/spend",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess],
    )
    def ai_spend(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        if not get_cached_instance_license():
            raise NotFound("AI credits need PostHog Cloud.")
        organization = self._get_org_required()
        start, end = ai_spend_period(organization, request.validated_query_data["period"], timezone.now())
        try:
            spend = get_org_spend(str(organization.id), start, end)
        except AIGatewayInternalError as error:
            logger.warning("ai_spend_gateway_unavailable", organization_id=str(organization.id))
            raise AISpendUnavailable() from error
        answer = AISpendResponseSerializer(data={**spend, "period_start": start, "period_end": end})
        if not answer.is_valid():
            logger.warning(
                "ai_spend_gateway_answer_invalid", organization_id=str(organization.id), errors=answer.errors
            )
            raise AISpendUnavailable()
        return Response(answer.data)

    @validated_request(responses={200: OpenApiResponse(response=AICreditCardResponseSerializer)})
    @action(
        methods=["GET"],
        detail=False,
        url_path="ai_credits/card",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess],
    )
    def ai_credit_card(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        answer = self._ai_credits(lambda manager, organization: manager.ai_credit_card(organization))
        return Response(AICreditCardResponseSerializer(answer).data)

    @validated_request(
        query_serializer=AICreditQuoteRequestSerializer,
        responses={200: OpenApiResponse(response=AICreditQuoteResponseSerializer)},
    )
    @action(
        methods=["GET"],
        detail=False,
        url_path="ai_credits/quote",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess, BillingNotManagedByPartner],
    )
    def ai_credit_quote(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        amount_usd = str(request.validated_query_data["amount_usd"])
        answer = self._ai_credits(
            lambda manager, organization: manager.ai_credit_quote(organization, amount_usd),
            bad_request=AICreditsNoCard,
            unavailable=AICreditsTaxUnavailable,
        )
        return Response(AICreditQuoteResponseSerializer(answer).data)

    @validated_request(
        request_serializer=AICreditPurchaseRequestSerializer,
        responses={200: OpenApiResponse(response=AICreditPurchaseResponseSerializer)},
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="ai_credits/purchase",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess, BillingNotManagedByPartner],
    )
    def ai_credit_purchase(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        data = request.validated_data
        purchase = {
            "amount_usd": str(data["amount_usd"]),
            "total_usd": str(data["total_usd"]),
            "idempotency_key": data["idempotency_key"],
        }
        answer = self._ai_credits(
            lambda manager, organization: manager.purchase_ai_credit(organization, purchase),
            bad_request=AICreditsNoCard,
            unavailable=AICreditsPurchaseUnfinished,
        )
        return Response(AICreditPurchaseResponseSerializer(answer).data)

    @extend_schema(parameters=[BillingUsageRequestSerializer])
    @action(
        methods=["GET"],
        detail=False,
        url_path="usage",
        permission_classes=[permissions.IsAuthenticated, HasBillingUsageSpendReadAccess],
        responses={200: BillingTimeSeriesResponseSerializer},
    )
    def usage(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        return self._usage_or_spend_response(request, self.get_billing_manager().get_usage_data)

    @action(
        methods=["GET"],
        detail=False,
        url_path="usage/team_options",
        permission_classes=[permissions.IsAuthenticated, HasBillingUsageSpendReadAccess],
        responses={200: BillingTeamOptionsResponseSerializer},
    )
    def usage_team_options(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        """The project ids the project filter offers, loaded apart from the charts.

        Scoped the way the charts are: a member without billing access sees only the projects
        they can see.
        """
        organization = self._get_org_required()
        scoped_team_ids = self._scoped_team_ids_for_usage_spend_request(request, organization, {})
        try:
            res = self.get_billing_manager().get_usage_team_options(organization)
        except Exception as e:  # noqa: BLE001 - a failure here empties the filter and must not fail the page
            logger.warning("billing_team_options_unavailable", organization_id=str(organization.id), error=str(e)[:200])
            res = {}
        options = res.get("team_id_options") or [] if isinstance(res, dict) else []
        if scoped_team_ids is not None:
            scoped_team_id_set = set(scoped_team_ids)
            options = [team_id for team_id in options if team_id in scoped_team_id_set]
        return Response({"team_id_options": options}, status=status.HTTP_200_OK)

    @extend_schema(parameters=[BillingUsageRequestSerializer])
    @action(
        methods=["GET"],
        detail=False,
        url_path="spend",
        permission_classes=[permissions.IsAuthenticated, HasBillingUsageSpendReadAccess],
        responses={200: BillingTimeSeriesResponseSerializer},
    )
    def spend(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        """Endpoint to fetch spend data (proxy to billing service)."""
        return self._usage_or_spend_response(request, self.get_billing_manager().get_spend_data)

    @extend_schema(parameters=[BillingUsageRequestSerializer])
    @action(
        methods=["GET"],
        detail=False,
        url_path="usage/export",
        permission_classes=[permissions.IsAuthenticated, HasBillingUsageSpendReadAccess],
        throttle_classes=[BillingExportThrottle],
    )
    def usage_export(self, request: Request, *args: Any, **kwargs: Any) -> StreamingHttpResponse:
        """Download the usage breakdown as CSV, honouring the requested project cap."""
        return self._csv_export_response(request, self.get_billing_manager().get_usage_csv, "posthog_usage.csv")

    @extend_schema(parameters=[BillingUsageRequestSerializer])
    @action(
        methods=["GET"],
        detail=False,
        url_path="spend/export",
        permission_classes=[permissions.IsAuthenticated, HasBillingUsageSpendReadAccess],
        throttle_classes=[BillingExportThrottle],
    )
    def spend_export(self, request: Request, *args: Any, **kwargs: Any) -> StreamingHttpResponse:
        """Download the spend breakdown as CSV, honouring the requested project cap."""
        return self._csv_export_response(request, self.get_billing_manager().get_spend_csv, "posthog_spend.csv")

    def _csv_export_response(
        self,
        request: Request,
        csv_getter: Callable[[Organization, dict[str, Any]], Any],
        fallback_filename: str,
    ) -> StreamingHttpResponse:
        """Pass an export through to the billing service and stream the file back.

        The project cap is forwarded as sent, so the file matches what the person is looking at.
        Omitting it asks for every project.
        """
        organization = self._get_org_required()
        serializer = BillingUsageRequestSerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)
        self._check_requested_team_ids_belong_to_org(organization, serializer.validated_data.get("team_ids"))

        params_to_pass = {k: v for k, v in serializer.validated_data.items() if v is not None}
        # The same narrowing as the interactive endpoints: a member who can only see some projects
        # must not export the others. Export access is set per project too, like the page's
        # button, so the file carries only the projects the person may export. A member who may
        # export none of them gets a 403. An admin or owner has export access everywhere, which
        # is the case where nothing is scoped.
        scoped_team_ids = self._scoped_team_ids_for_usage_spend_request(request, organization, params_to_pass)
        if scoped_team_ids is not None:
            scoped_team_ids = self._exportable_team_ids(request, organization, scoped_team_ids)
            if not scoped_team_ids:
                raise PermissionDenied("You do not have permission to export data.")
            params_to_pass["team_ids"] = json.dumps(scoped_team_ids)
        # No teams_map: the names go into the file as it streams back, in _rewrite_csv_labels.
        teams_map = self._get_teams_map(organization, scoped_team_ids)

        # Taken before billing is asked, so a refused export costs billing nothing, and held
        # until the download ends: the body below gives it back.
        slot = _take_export_stream_slot(request.user)
        try:
            try:
                upstream = csv_getter(organization, params_to_pass)
            except requests.Timeout:
                raise BillingQueryTimeout()
            except APIException:
                raise
            except Exception as e:
                self._raise_billing_error(e, organization)
        except BaseException:
            _release_export_stream_slot(slot)
            raise
        lines = _rewrite_csv_labels(upstream.iter_content(chunk_size=8192), teams_map)
        accepts_gzip = "gzip" in request.META.get("HTTP_ACCEPT_ENCODING", "").lower()
        # Every database read is done by now and the body does none, so the request's
        # connection is released before the download starts.
        response = streaming_response(
            _released_after(_stream_chunks(upstream, _gzip_stream(lines) if accepts_gzip else lines), slot),
            content_type=upstream.headers.get("Content-Type", "text/csv"),
        )
        if accepts_gzip:
            response["Content-Encoding"] = "gzip"
        patch_vary_headers(response, ("Accept-Encoding",))
        response["Content-Disposition"] = upstream.headers.get(
            "Content-Disposition", f'attachment; filename="{fallback_filename}"'
        )
        return response

    def _usage_or_spend_response(
        self,
        request: Request,
        billing_data_getter: Callable[[Organization, dict[str, Any]], Any],
    ) -> HttpResponse:
        organization = self._get_org_required()
        serializer = BillingUsageRequestSerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)
        self._check_requested_team_ids_belong_to_org(organization, serializer.validated_data.get("team_ids"))

        try:
            params_to_pass = {k: v for k, v in serializer.validated_data.items() if v is not None}
            scoped_team_ids = self._scoped_team_ids_for_usage_spend_request(request, organization, params_to_pass)
            teams_map = self._get_teams_map(organization, scoped_team_ids)

            if scoped_team_ids is not None:
                params_to_pass["team_ids"] = json.dumps(scoped_team_ids)

            res = billing_data_getter(organization, params_to_pass)
            if isinstance(res, dict):
                _resolve_team_labels(res.get("results"), teams_map)
                if scoped_team_ids is not None and "team_id_options" in res:
                    # Billing still lists every project here for older callers; a member sees only theirs.
                    scoped_team_id_set = set(scoped_team_ids)
                    res["team_id_options"] = [
                        team_id for team_id in (res.get("team_id_options") or []) if team_id in scoped_team_id_set
                    ]
            return Response(res, status=status.HTTP_200_OK)
        except requests.Timeout:
            # See BillingQueryTimeout: the person is told what to change, not shown a 500.
            logger.warning(
                "billing_timeseries_timeout",
                organization_id=str(organization.id),
                breakdowns=params_to_pass.get("breakdowns"),
                team_ids_count=len(self._parse_team_ids(params_to_pass.get("team_ids"))),
            )
            raise BillingQueryTimeout()
        except APIException:
            raise
        except Exception as e:
            self._raise_billing_error(e, organization)

    @staticmethod
    def _raise_billing_error(error: Exception, organization: Organization) -> NoReturn:
        """Raise the named exception for an error billing returned on a usage, spend or export request.

        handle_billing_service_error raises with the status in its message and the parsed body as
        the third argument. Known guidance and validation codes use controlled messages because
        upstream detail can contain caller input or internal data. Unknown errors remain a generic
        400 or 502. An exception of any other shape is not billing's answer and is re-raised as it is.
        """
        status_match = re.search(r"status code: (\d+)", str(error.args[0]) if error.args else "")
        if not status_match:
            raise error
        upstream_status = int(status_match.group(1))
        body = error.args[2] if len(error.args) > 2 else None
        code = body.get("code") if isinstance(body, dict) else None
        logger.warning(
            "billing_query_error",
            organization_id=str(organization.id),
            upstream_status=upstream_status,
            code=code,
            body=str(body)[:500],
        )
        if code == "permission_denied":
            # Billing evaluates the same permission from its own cache, so flag rollout windows
            # can still return a downstream permission denial.
            raise PermissionDenied(HasBillingUsageSpendReadAccess.message) from error
        if isinstance(code, str) and code in BILLING_GUIDANCE_ERRORS:
            raise BILLING_GUIDANCE_ERRORS[code]() from error
        if upstream_status == 400 and isinstance(body, dict) and body.get("type") == "validation_error":
            field = body.get("attr")
            if (
                isinstance(field, str)
                and field in BillingUsageRequestSerializer().fields
                and isinstance(code, str)
                and code in BILLING_VALIDATION_ERROR_MESSAGES
            ):
                raise ValidationError({field: [BILLING_VALIDATION_ERROR_MESSAGES[code]]}, code=code) from error
        if 400 <= upstream_status < 500:
            raise BillingQueryRejected() from error
        raise BillingServiceError() from error

    def _exportable_team_ids(
        self, request: Request, organization: Organization, team_ids: Sequence[int]
    ) -> Sequence[int]:
        """The given projects on which the person has editor access to exports."""
        if not isinstance(request.user, User):
            return sorted(team_ids)
        return exportable_team_ids(request.user, organization, team_ids)

    def _scoped_team_ids_for_usage_spend_request(
        self, request: Request, organization: Organization, params_to_pass: dict[str, Any]
    ) -> Optional[Sequence[int]]:
        if not isinstance(request.user, User) or user_has_billing_access(request.user, organization):
            return None

        accessible_team_ids = self._team_ids_visible_to_user_in_org(request.user, organization)
        token_scoped_team_ids = get_authenticator_scoped_team_ids(getattr(request, "successful_authenticator", None))
        if token_scoped_team_ids is not None:
            accessible_team_ids = sorted(set(accessible_team_ids).intersection(token_scoped_team_ids))

        if not accessible_team_ids:
            raise PermissionDenied(BILLING_PROJECT_ACCESS_DENIED_MESSAGE)

        requested_team_ids = self._parse_team_ids(params_to_pass.get("team_ids"))
        if not requested_team_ids:
            return accessible_team_ids

        scoped_team_ids = sorted(set(requested_team_ids).intersection(accessible_team_ids))
        if not scoped_team_ids:
            raise PermissionDenied(BILLING_PROJECT_ACCESS_DENIED_MESSAGE)

        return scoped_team_ids

    def _team_ids_visible_to_user_in_org(self, user: User, organization: Organization) -> Sequence[int]:
        return list(
            visible_teams_for_user(
                organization,
                UserAccessControl(user=user, organization_id=str(organization.id)),
                UserPermissions(user=user),
            )
            .order_by("id")
            .values_list("id", flat=True)
        )

    def _parse_team_ids(self, team_ids: Optional[str]) -> Sequence[int]:
        if not team_ids:
            return []

        parsed_team_ids = json.loads(team_ids)
        if not isinstance(parsed_team_ids, list):
            raise ValidationError({"team_ids": "Value must be a JSON array of numeric team IDs."})

        return [team_id for team_id in parsed_team_ids if isinstance(team_id, int) and not isinstance(team_id, bool)]

    def _get_teams_map(self, organization: Organization, team_ids: Optional[Sequence[int]] = None) -> dict[int, str]:
        """
        Safely build a mapping of team.id to team.name for the org, optionally limited to team_ids.
        Return empty dict on failure.
        """
        try:
            teams = Team.objects.filter(organization=organization)
            if team_ids is not None:
                teams = teams.filter(id__in=team_ids)
            return {team.id: team.name for team in teams}
        except Exception as e:
            capture_exception(e, {"organization_id": organization.id})
            return {}

    def _check_requested_team_ids_belong_to_org(self, organization: Organization, team_ids: Optional[str]) -> None:
        if not team_ids:
            return

        requested_team_ids = set(json.loads(team_ids))
        if not requested_team_ids:
            return

        # Billing lists every project that has reported usage for the organization, so a request
        # can name a project PostHog has since deleted. Billing scopes the read to the organization
        # in the token, so such an id only reads that organization's own history. What must not
        # pass is a project that belongs to another organization.
        foreign_team_ids = (
            Team.objects.filter(id__in=requested_team_ids)
            .exclude(organization=organization)
            .values_list("id", flat=True)
        )

        if foreign_team_ids.exists():
            raise PermissionDenied("One or more requested projects are not in this organization.")

    def _get_org(self) -> Optional[Organization]:
        if self.request.user.is_anonymous:
            return None

        try:
            if self.action in self.payment_actions or (
                self.action == "list" and "organization_id" in self.request.query_params
            ):
                return self.organization
            return self.team.organization
        except Exception:
            return None

    def _get_org_required(self) -> Organization:
        org = self._get_org()

        if not org:
            raise Exception("You cannot interact with the billing service without an organization configured.")

        return org
