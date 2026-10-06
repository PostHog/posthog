"""Billing for a provisioning partner that pays for its customers, run by admins of the partner's own
verified PostHog organization.

The partner itself reaches the same billing through the provisioning API, because its provisioning OAuth
tokens are scoped to teams and cannot reach organization routes.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.validators import URLValidator
from django.db import models
from django.db.models import QuerySet

import requests
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.cloud_utils import get_cached_instance_license
from posthog.dataclasses import frozen
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import OAuthApplication
from posthog.models.user import User
from posthog.permissions import OrganizationAdminReadPermissions, TimeSensitiveActionPermission
from posthog.rate_limit import (
    BillingReadBurstRateThrottle,
    BillingReadSustainedRateThrottle,
    PersonalApiKeyOrUserRateThrottle,
)
from posthog.utils import get_trusted_client_ip

from ee.billing.billing_manager import BillingManager, BillingServiceResponseError

PORTAL_DEFAULT_RETURN_PATH = "/organization/billing"
SETTLEMENT_ID_PATTERN = r"[A-Za-z0-9_-]+"
UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"


def _usd_amount_field(help_text: str) -> serializers.DecimalField:
    return serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0"),
        required=False,
        allow_null=True,
        help_text=help_text,
    )


def _usd_limits_field(help_text: str, **kwargs: Any) -> serializers.DictField:
    return serializers.DictField(
        child=serializers.IntegerField(min_value=0, allow_null=True), help_text=help_text, **kwargs
    )


class PartnerPayerUpdateSerializer(serializers.Serializer):
    webhook_url = serializers.URLField(
        required=False,
        allow_null=True,
        max_length=2048,
        validators=[URLValidator(schemes=["https"], message="Enter an HTTPS URL.")],
        help_text=(
            "HTTPS URL that receives the partner's billing events, signed with the webhook secret. "
            "Null removes the webhook."
        ),
    )
    spend_alert_usd = _usd_amount_field(
        "Month-to-date spend in US dollars, across every organization the partner pays for, at which billing "
        "sends a spend alert. Null turns the alert off."
    )
    spend_cap_usd = _usd_amount_field(
        "Month-to-date spend in US dollars, across every organization the partner pays for, at which billing "
        "caps further usage. Null removes the cap."
    )


class PartnerPayerAdminUpdateSerializer(PartnerPayerUpdateSerializer):
    default_limits_usd = _usd_limits_field(
        "Default monthly spend limit in whole US dollars per product key. A default applies to every organization "
        "the partner pays for that has no limit of its own for that product, including organizations that are "
        "already linked. Null for a product removes its default. Products left out keep their default.",
        required=False,
    )


class PartnerPayerOrganizationLimitsSerializer(serializers.Serializer):
    custom_limits_usd = _usd_limits_field(
        "Monthly spend limit in whole US dollars per product key for this organization. It replaces the "
        "partner's default for that product. Null for a product means no limit, even when the partner has a "
        "default for it. Products left out keep their limit."
    )


class PartnerPayerPortalRequestSerializer(serializers.Serializer):
    return_path = serializers.CharField(
        required=False,
        default=PORTAL_DEFAULT_RETURN_PATH,
        max_length=2048,
        help_text="Path in PostHog that the billing portal returns to. Defaults to the billing page.",
    )

    def validate_return_path(self, value: str) -> str:
        # The return URL is SITE_URL followed by this path, so a path that starts with a slash cannot
        # send the browser to another site.
        if not value.startswith("/"):
            raise serializers.ValidationError("Enter a path that starts with /.")
        return value


class PartnerPayerPageQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        required=False, min_value=1, max_value=100, help_text="Number of results to return, from 1 to 100."
    )
    offset = serializers.IntegerField(required=False, min_value=0, help_text="Number of results to skip.")


class PartnerPayerInvoiceStatus(models.TextChoices):
    OPEN = "open"
    PAID = "paid"
    UNCOLLECTIBLE = "uncollectible"
    VOID = "void"


class PartnerPayerInvoicesQuerySerializer(PartnerPayerPageQuerySerializer):
    organization_id = serializers.UUIDField(required=False, help_text="Only return this organization's invoices.")
    status = serializers.ChoiceField(
        choices=PartnerPayerInvoiceStatus.choices, required=False, help_text="Only return invoices in this status."
    )

    def validate_organization_id(self, value: uuid.UUID) -> str:
        return str(value)


class PartnerPayerApplicationSerializer(serializers.Serializer):
    id = serializers.UUIDField(
        read_only=True, help_text="ID of the partner's OAuth application. The other partner billing routes take it."
    )
    name = serializers.CharField(read_only=True, help_text="Name of the partner application.")
    logo_uri = serializers.URLField(
        read_only=True, allow_null=True, help_text="URL of the partner application's logo, or null."
    )


class PartnerPayerAddressSerializer(serializers.Serializer):
    line1 = serializers.CharField(required=False, allow_null=True, help_text="First line of the address.")
    line2 = serializers.CharField(required=False, allow_null=True, help_text="Second line of the address.")
    city = serializers.CharField(required=False, allow_null=True, help_text="City.")
    state = serializers.CharField(required=False, allow_null=True, help_text="State, county, province, or region.")
    postal_code = serializers.CharField(required=False, allow_null=True, help_text="Postal code.")
    country = serializers.CharField(required=False, allow_null=True, help_text="Two-letter ISO country code.")


class PartnerPayerTaxIdSerializer(serializers.Serializer):
    type = serializers.CharField(required=False, help_text="Tax ID type, for example `eu_vat`.")
    value = serializers.CharField(required=False, help_text="The tax ID.")


class PartnerPayerBillingDetailsSerializer(serializers.Serializer):
    address = PartnerPayerAddressSerializer(
        required=False, allow_null=True, help_text="Billing address on the payer's invoices."
    )
    tax_ids = PartnerPayerTaxIdSerializer(many=True, required=False, help_text="Tax IDs on the payer's invoices.")


class PartnerPayerWebhookSerializer(serializers.Serializer):
    url = serializers.URLField(
        required=False, allow_null=True, help_text="URL that receives the partner's billing events, or null."
    )
    secret_created_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="When the current webhook signing secret was created, or null when there is none.",
    )


class PartnerPayerSpendSerializer(serializers.Serializer):
    month_to_date_usd = serializers.CharField(
        required=False,
        allow_null=True,
        help_text=(
            "Spend this month across the partner's organizations as of billing's last daily count, as a decimal "
            "string in US dollars. Null until billing has counted this month."
        ),
    )
    alert_usd = serializers.CharField(
        required=False, allow_null=True, help_text="Spend alert threshold, as a decimal string in US dollars, or null."
    )
    cap_usd = serializers.CharField(
        required=False, allow_null=True, help_text="Spend cap, as a decimal string in US dollars, or null."
    )
    capped = serializers.BooleanField(required=False, help_text="Whether this month's spend has reached the cap.")


class PartnerPayerStatusSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, help_text="Name on the payer's invoices.")
    billing_enabled = serializers.BooleanField(
        required=False, help_text="Whether billing charges the partner for its organizations."
    )
    has_payment_method = serializers.BooleanField(
        required=False, help_text="Whether the payer has a payment method on file."
    )
    billing_details = PartnerPayerBillingDetailsSerializer(
        required=False, help_text="Address and tax IDs on the payer's invoices."
    )
    organization_count = serializers.IntegerField(
        required=False, help_text="Number of organizations the partner pays for."
    )
    webhook = PartnerPayerWebhookSerializer(required=False, help_text="Where billing sends the partner's events.")
    past_due = serializers.BooleanField(
        required=False, help_text="Whether the payer owes a settlement that billing could not charge."
    )
    spend = PartnerPayerSpendSerializer(required=False, help_text="This month's spend, and its alert and cap.")
    default_limits_usd = serializers.DictField(
        child=serializers.IntegerField(allow_null=True),
        required=False,
        help_text=(
            "Default monthly spend limit in whole US dollars per product key. A default applies to every "
            "organization the partner pays for that has no limit of its own for that product."
        ),
    )


class PartnerPayerPortalSerializer(serializers.Serializer):
    url = serializers.URLField(help_text="Billing portal URL to send the person's browser to. It expires shortly.")


class PartnerPayerWebhookSecretSerializer(serializers.Serializer):
    secret = serializers.CharField(
        help_text="The new webhook signing secret, in `whsec_` format. Billing returns it only once."
    )
    created_at = serializers.DateTimeField(help_text="When the secret was created.")


class PartnerPayerTestEventSerializer(serializers.Serializer):
    event_id = serializers.CharField(help_text="ID of the test event, also sent as its `webhook-id` header.")


class PartnerPayerOrganizationSerializer(serializers.Serializer):
    organization_id = serializers.CharField(help_text="ID of the PostHog organization.")
    name = serializers.CharField(required=False, help_text="Name of the organization.")
    linked_at = serializers.DateTimeField(
        required=False, allow_null=True, help_text="When the partner started paying for the organization."
    )
    detached_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="When the organization stopped being paid for by the partner, or null.",
    )
    custom_limits_usd = serializers.DictField(
        child=serializers.IntegerField(allow_null=True),
        required=False,
        help_text=(
            "This organization's own monthly spend limits in whole US dollars per product key. Null means no "
            "limit. A product that is not listed follows the partner's default limits."
        ),
    )


class PartnerPayerOrganizationListSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Total number of organizations.")
    results = PartnerPayerOrganizationSerializer(many=True, help_text="This page of organizations.")


class PartnerPayerInvoiceSerializer(serializers.Serializer):
    invoice_id = serializers.CharField(help_text="ID of the invoice.")
    organization_id = serializers.CharField(required=False, help_text="ID of the organization the invoice is for.")
    period_start = serializers.DateTimeField(required=False, allow_null=True, help_text="Start of the billing period.")
    period_end = serializers.DateTimeField(required=False, allow_null=True, help_text="End of the billing period.")
    amount_cents = serializers.IntegerField(
        required=False, help_text="What the payer owes for this invoice, after credits, in the currency's minor unit."
    )
    currency = serializers.CharField(
        required=False, help_text="Three-letter ISO currency code in upper case, for example `USD`."
    )
    status = serializers.CharField(required=False, help_text="Invoice status, for example `open` or `paid`.")
    settlement_id = serializers.CharField(
        required=False, allow_null=True, help_text="ID of the settlement that pays this invoice, or null."
    )
    pdf_url = serializers.URLField(required=False, allow_null=True, help_text="URL of the invoice PDF, or null.")


class PartnerPayerInvoiceListSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Total number of invoices.")
    results = PartnerPayerInvoiceSerializer(many=True, help_text="This page of invoices.")


class PartnerPayerSettlementSerializer(serializers.Serializer):
    settlement_id = serializers.CharField(help_text="ID of the settlement.")
    period_start = serializers.DateTimeField(required=False, allow_null=True, help_text="Start of the billing period.")
    period_end = serializers.DateTimeField(required=False, allow_null=True, help_text="End of the billing period.")
    amount_cents = serializers.IntegerField(
        required=False, help_text="Cash charge after settlement credits, in the currency's minor unit."
    )
    gross_amount_cents = serializers.IntegerField(
        required=False,
        help_text="Total allocated to the organization invoices before settlement credits, in the currency's minor unit.",
    )
    credit_amount_cents = serializers.IntegerField(
        required=False, help_text="Adjustment credits applied to this settlement, in the currency's minor unit."
    )
    currency = serializers.CharField(
        required=False, help_text="Three-letter ISO currency code in upper case, for example `USD`."
    )
    status = serializers.CharField(required=False, help_text="Settlement status, for example `paid` or `failed`.")
    attempt_count = serializers.IntegerField(required=False, help_text="Number of times billing tried the charge.")
    next_attempt_at = serializers.DateTimeField(
        required=False, allow_null=True, help_text="When billing tries the charge again, or null."
    )
    paid_at = serializers.DateTimeField(
        required=False, allow_null=True, help_text="When the charge succeeded, or null."
    )


class PartnerPayerSettlementListSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Total number of settlements.")
    results = PartnerPayerSettlementSerializer(many=True, help_text="This page of settlements.")


class PartnerPayerSettlementInvoiceSerializer(PartnerPayerInvoiceSerializer):
    amount_cents = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="What the payer owes for this invoice, after credits, in the currency's minor unit, or null when billing has not recorded the invoice yet.",
    )
    charged_cents = serializers.IntegerField(
        required=False,
        help_text="Amount allocated to this invoice before settlement credits, in the currency's minor unit. This is not the invoice's share of the cash charge.",
    )


class PartnerPayerSettlementDetailSerializer(PartnerPayerSettlementSerializer):
    invoices = PartnerPayerSettlementInvoiceSerializer(
        many=True, required=False, help_text="The organization invoices that the settlement pays."
    )


@frozen
class PartnerBillingRefusal:
    status: int
    code: str
    message: str
    field: str | None = None


BILLING_UNAVAILABLE = PartnerBillingRefusal(
    status=502, code="billing_unavailable", message="Billing could not answer this request. Try again in a moment."
)


def classify_partner_billing_error(error: Exception, fields: Collection[str] = ()) -> PartnerBillingRefusal:
    """How PostHog answers a payer call that billing refused or could not serve.

    Billing's own message never reaches the caller, because it is written for billing's API and can carry
    detail the caller must not see. A rejected value names its field only when the caller sent that field.
    A 401 or a 5xx means PostHog and billing disagree or billing is down, which the caller cannot fix.
    """
    if not isinstance(error, BillingServiceResponseError):
        return BILLING_UNAVAILABLE
    if error.status_code == 404:
        return PartnerBillingRefusal(status=404, code="not_found", message="Billing has no record of this.")
    if error.status_code == 403:
        return PartnerBillingRefusal(
            status=403,
            code="forbidden",
            message="Billing for this partner is managed by a different PostHog organization.",
        )
    if error.status_code == 409:
        return PartnerBillingRefusal(
            status=409, code="conflict", message="Billing cannot make this change now. Reload and try again."
        )
    if error.status_code == 400:
        # Billing renders nested field errors with the path joined by "__", so the first part names the field.
        attr = error.body.get("attr") if isinstance(error.body, dict) else None
        field = attr.split("__")[0] if isinstance(attr, str) else None
        if field is not None and field in fields:
            return PartnerBillingRefusal(
                status=400,
                code="invalid_input",
                message="Billing rejected this value. Check its format and allowed values.",
                field=field,
            )
        return PartnerBillingRefusal(status=400, code="billing_rejected", message="Billing rejected this request.")
    return BILLING_UNAVAILABLE


def billing_json(validated_data: dict[str, Any]) -> dict[str, Any]:
    return {key: str(value) if isinstance(value, Decimal) else value for key, value in validated_data.items()}


class MalformedBillingResponse(Exception):
    pass


def serialize_billing_response(serializer_class: type[serializers.Serializer], payload: Any) -> dict[str, Any]:
    # DRF raises one of these when a billing 200 lacks a key the contract requires or holds a value of the wrong type.
    try:
        return serializer_class(payload).data
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise MalformedBillingResponse(f"Billing's response does not fit {serializer_class.__name__}") from error


PARTNER_BILLING_CALL_ERRORS = (BillingServiceResponseError, MalformedBillingResponse, requests.RequestException)


class PartnerBillingRefusalError(APIException):
    def __init__(self, refusal: PartnerBillingRefusal) -> None:
        super().__init__(detail=refusal.message, code=refusal.code)
        self.status_code = refusal.status


@contextmanager
def _billing_refusals(application: OAuthApplication, fields: Collection[str] = ()) -> Iterator[None]:
    try:
        yield
    except PARTNER_BILLING_CALL_ERRORS as error:
        refusal = classify_partner_billing_error(error, fields)
        capture_exception(error, {"partner_application_id": str(application.id), "refusal_code": refusal.code})
        if refusal.field is not None:
            raise ValidationError({refusal.field: [refusal.message]}, code=refusal.code) from error
        raise PartnerBillingRefusalError(refusal) from error


SETTLEMENT_ID_PARAMETER = OpenApiParameter(
    "settlement_id", OpenApiTypes.STR, OpenApiParameter.PATH, description="ID of the settlement."
)
CUSTOMER_ORGANIZATION_ID_PARAMETER = OpenApiParameter(
    "customer_organization_id",
    OpenApiTypes.UUID,
    OpenApiParameter.PATH,
    description="ID of an organization the partner pays for.",
)


class PartnerBillingTestEventBurstThrottle(PersonalApiKeyOrUserRateThrottle):
    scope = "partner_billing_test_event_burst"
    rate = "5/minute"


class PartnerBillingTestEventSustainedThrottle(PersonalApiKeyOrUserRateThrottle):
    scope = "partner_billing_test_event_sustained"
    rate = "30/hour"


@extend_schema(extensions={"x-product": "billing"})
class PartnerBillingViewSet(TeamAndOrgViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    # Session only. A partner's own machine path is the provisioning API, where it signs as itself, and a
    # personal API key that can read billing must not also rotate the webhook secret or raise a spend cap.
    scope_object = "INTERNAL"
    permission_classes = [OrganizationAdminReadPermissions, TimeSensitiveActionPermission]
    # A test event changes no credential, limit or charge, so it skips the recent-login window.
    time_sensitive_allow_actions = ["test_event"]
    throttle_classes = [BillingReadBurstRateThrottle, BillingReadSustainedRateThrottle]
    queryset = OAuthApplication.objects.all()
    serializer_class = PartnerPayerApplicationSerializer
    pagination_class = None

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(organization=self.organization, _provisioning_config__pays_for_customers=True).order_by(
            "name", "id"
        )

    def _billing_manager(self) -> BillingManager:
        return BillingManager(get_cached_instance_license(), ip_address=get_trusted_client_ip(self.request))

    def _report_action(self, application: OAuthApplication, action_name: str) -> None:
        if isinstance(self.request.user, User):
            report_user_action(
                self.request.user,
                "partner billing action",
                {"action": action_name, "partner_application_id": str(application.id)},
                organization=self.organization,
            )

    @extend_schema(
        operation_id="partner_billing_retrieve",
        summary="Get the partner's billing status",
        responses={200: PartnerPayerStatusSerializer},
    )
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        application = self.get_object()
        with _billing_refusals(application):
            payer = serialize_billing_response(
                PartnerPayerStatusSerializer, self._billing_manager().get_payer(application)
            )
        return Response(payer)

    @extend_schema(
        operation_id="partner_billing_partial_update",
        summary="Change the partner's webhook, spend alert, spend cap or default limits",
        request=PartnerPayerAdminUpdateSerializer,
        responses={200: PartnerPayerStatusSerializer},
    )
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        application = self.get_object()
        serializer = PartnerPayerAdminUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with _billing_refusals(application, fields=serializer.validated_data.keys()):
            payer = serialize_billing_response(
                PartnerPayerStatusSerializer,
                self._billing_manager().update_payer(application, billing_json(serializer.validated_data)),
            )
        self._report_action(application, "settings_updated")
        return Response(payer)

    @extend_schema(
        operation_id="partner_billing_portal_create",
        summary="Open the payer's billing portal to manage the payment method and billing details",
        request=PartnerPayerPortalRequestSerializer,
        responses={200: PartnerPayerPortalSerializer},
    )
    @action(methods=["POST"], detail=True)
    def portal(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        application = self.get_object()
        serializer = PartnerPayerPortalRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return_url = f"{settings.SITE_URL}{serializer.validated_data['return_path']}"
        with _billing_refusals(application):
            portal = serialize_billing_response(
                PartnerPayerPortalSerializer,
                self._billing_manager().create_payer_portal_session(application, return_url),
            )
        self._report_action(application, "portal_opened")
        return Response(portal)

    @extend_schema(
        operation_id="partner_billing_webhook_secret_create",
        summary="Replace the webhook signing secret",
        description="The previous secret stops signing events. The response is the only time the secret is shown.",
        request=None,
        responses={200: PartnerPayerWebhookSecretSerializer},
    )
    @action(methods=["POST"], detail=True)
    def webhook_secret(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        application = self.get_object()
        with _billing_refusals(application):
            secret = serialize_billing_response(
                PartnerPayerWebhookSecretSerializer, self._billing_manager().rotate_payer_webhook_secret(application)
            )
        self._report_action(application, "webhook_secret_rotated")
        return Response(secret, headers={"Cache-Control": "no-store"})

    @extend_schema(
        operation_id="partner_billing_test_event_create",
        summary="Send a test event to the partner's webhook",
        request=None,
        responses={200: PartnerPayerTestEventSerializer},
    )
    # Every test event makes billing deliver a request to the partner's webhook, so each person gets the budget
    # the partner's own test event route has, on top of the shared billing budget.
    @action(
        methods=["POST"],
        detail=True,
        throttle_classes=[
            BillingReadBurstRateThrottle,
            BillingReadSustainedRateThrottle,
            PartnerBillingTestEventBurstThrottle,
            PartnerBillingTestEventSustainedThrottle,
        ],
    )
    def test_event(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        application = self.get_object()
        with _billing_refusals(application):
            event = serialize_billing_response(
                PartnerPayerTestEventSerializer, self._billing_manager().send_payer_test_event(application)
            )
        self._report_action(application, "test_event_sent")
        return Response(event)

    @extend_schema(
        operation_id="partner_billing_organization_list",
        summary="List the organizations the partner pays for",
        parameters=[PartnerPayerPageQuerySerializer],
        responses={200: PartnerPayerOrganizationListSerializer},
    )
    @action(methods=["GET"], detail=True)
    def organizations(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        application = self.get_object()
        query = PartnerPayerPageQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        with _billing_refusals(application):
            organizations = serialize_billing_response(
                PartnerPayerOrganizationListSerializer,
                self._billing_manager().list_payer_organizations(application, **query.validated_data),
            )
        return Response(organizations)

    @extend_schema(
        operation_id="partner_billing_organization_limits_partial_update",
        summary="Set an organization's monthly spend limits",
        parameters=[CUSTOMER_ORGANIZATION_ID_PARAMETER],
        request=PartnerPayerOrganizationLimitsSerializer,
        responses={200: PartnerPayerOrganizationSerializer},
    )
    @action(
        methods=["PATCH"],
        detail=True,
        url_path=rf"organizations/(?P<customer_organization_id>{UUID_PATTERN})/limits",
    )
    def organization_limits(
        self, request: Request, customer_organization_id: str, *args: Any, **kwargs: Any
    ) -> Response:
        application = self.get_object()
        serializer = PartnerPayerOrganizationLimitsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with _billing_refusals(application, fields=serializer.validated_data.keys()):
            organization = serialize_billing_response(
                PartnerPayerOrganizationSerializer,
                self._billing_manager().update_payer_organization_limits(
                    application,
                    str(uuid.UUID(customer_organization_id)),
                    serializer.validated_data["custom_limits_usd"],
                ),
            )
        self._report_action(application, "organization_limits_updated")
        return Response(organization)

    @extend_schema(
        operation_id="partner_billing_invoices_list",
        summary="List the organization invoices the partner pays",
        parameters=[PartnerPayerInvoicesQuerySerializer],
        responses={200: PartnerPayerInvoiceListSerializer},
    )
    @action(methods=["GET"], detail=True)
    def invoices(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        application = self.get_object()
        query = PartnerPayerInvoicesQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        with _billing_refusals(application):
            invoices = serialize_billing_response(
                PartnerPayerInvoiceListSerializer,
                self._billing_manager().list_payer_invoices(application, **query.validated_data),
            )
        return Response(invoices)

    @extend_schema(
        operation_id="partner_billing_settlements_list",
        summary="List the partner's monthly settlements",
        parameters=[PartnerPayerPageQuerySerializer],
        responses={200: PartnerPayerSettlementListSerializer},
    )
    @action(methods=["GET"], detail=True)
    def settlements(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        application = self.get_object()
        query = PartnerPayerPageQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        with _billing_refusals(application):
            settlements = serialize_billing_response(
                PartnerPayerSettlementListSerializer,
                self._billing_manager().list_payer_settlements(application, **query.validated_data),
            )
        return Response(settlements)

    @extend_schema(
        operation_id="partner_billing_settlements_retrieve",
        summary="Get a settlement and the invoices it pays",
        parameters=[SETTLEMENT_ID_PARAMETER],
        responses={200: PartnerPayerSettlementDetailSerializer},
    )
    @action(methods=["GET"], detail=True, url_path=rf"settlements/(?P<settlement_id>{SETTLEMENT_ID_PATTERN})")
    def settlement(self, request: Request, settlement_id: str, *args: Any, **kwargs: Any) -> Response:
        application = self.get_object()
        with _billing_refusals(application):
            settlement = serialize_billing_response(
                PartnerPayerSettlementDetailSerializer,
                self._billing_manager().get_payer_settlement(application, settlement_id),
            )
        return Response(settlement)

    @extend_schema(
        operation_id="partner_billing_settlement_retry_create",
        summary="Charge a failed settlement again",
        parameters=[SETTLEMENT_ID_PARAMETER],
        request=None,
        responses={200: PartnerPayerSettlementSerializer},
    )
    @action(methods=["POST"], detail=True, url_path=rf"settlements/(?P<settlement_id>{SETTLEMENT_ID_PATTERN})/retry")
    def settlement_retry(self, request: Request, settlement_id: str, *args: Any, **kwargs: Any) -> Response:
        application = self.get_object()
        with _billing_refusals(application):
            settlement = serialize_billing_response(
                PartnerPayerSettlementSerializer,
                self._billing_manager().retry_payer_settlement(application, settlement_id),
            )
        self._report_action(application, "settlement_retried")
        return Response(settlement)
