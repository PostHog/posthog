"""Billing routes for a partner that pays for its customers.

Each route calls billing's payer API as the authenticated partner, pinned to the PostHog organization that
verified it. The billing portal, settlement retries and default limits are only on the partner billing
page in ee/api/partner_billing.py, for admins of that organization.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from typing import Any, cast

from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.cloud_utils import get_cached_instance_license
from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import OAuthApplication
from posthog.token_bucket import Budget
from posthog.utils import get_trusted_client_ip

from ee.api.agentic_provisioning.analytics import capture_provisioning_event
from ee.api.agentic_provisioning.authentication import PayerAuthentication
from ee.api.agentic_provisioning.exceptions import ProvisioningError
from ee.api.agentic_provisioning.ratelimits import FLAT_MULTIPLIERS, rate_limited, record_outbound_call
from ee.api.agentic_provisioning.serializers import first_error_message
from ee.api.agentic_provisioning.views.base import ProvisioningAPIView
from ee.api.partner_billing import (
    PARTNER_BILLING_CALL_ERRORS,
    PartnerPayerInvoiceListSerializer,
    PartnerPayerInvoicesQuerySerializer,
    PartnerPayerOrganizationLimitsSerializer,
    PartnerPayerOrganizationListSerializer,
    PartnerPayerOrganizationSerializer,
    PartnerPayerPageQuerySerializer,
    PartnerPayerSettlementDetailSerializer,
    PartnerPayerSettlementListSerializer,
    PartnerPayerStatusSerializer,
    PartnerPayerTestEventSerializer,
    PartnerPayerUpdateSerializer,
    PartnerPayerWebhookSecretSerializer,
    billing_json,
    classify_partner_billing_error,
    serialize_billing_response,
)
from ee.billing.billing_manager import BillingManager

DEFAULT_LIMITS_REFUSED_MESSAGE = (
    "default_limits_usd: This route cannot change default limits. An admin of your PostHog organization can "
    "change them in organization settings, under Partner billing."
)


class PayerAPIView(ProvisioningAPIView):
    authentication_classes = [PayerAuthentication]

    def payer(self, request: Request) -> OAuthApplication:
        partner = cast(OAuthApplication, request.auth)
        if partner.organization_id is None:
            raise ProvisioningError(
                "forbidden", "Partner billing needs a verified PostHog organization for this partner", status=403
            )
        return partner

    def billing_manager(self, request: Request) -> BillingManager:
        return BillingManager(get_cached_instance_license(), ip_address=get_trusted_client_ip(request))

    def validated_query(self, serializer_class: type[serializers.Serializer], request: Request) -> dict[str, Any]:
        serializer = serializer_class(data=request.query_params)
        if not serializer.is_valid():
            raise ProvisioningError("invalid_request", first_error_message(serializer.errors))
        return dict(serializer.validated_data)

    @contextmanager
    def billing_call(self, partner: OAuthApplication, action: str, fields: Collection[str] = ()) -> Iterator[None]:
        record_outbound_call(self.request)
        try:
            yield
        except PARTNER_BILLING_CALL_ERRORS as error:
            refusal = classify_partner_billing_error(error, fields)
            capture_exception(error, {"partner_application_id": str(partner.id), "refusal_code": refusal.code})
            capture_provisioning_event("payer", "error", partner=partner, action=action, error_code=refusal.code)
            if refusal.field is not None:
                raise ProvisioningError(
                    "invalid_request", f"{refusal.field}: {refusal.message}", status=refusal.status
                ) from error
            raise ProvisioningError(refusal.code, refusal.message, status=refusal.status) from error
        capture_provisioning_event("payer", "success", partner=partner, action=action)


class PayerView(PayerAPIView):
    @rate_limited("payer_reads")
    def get(self, request: Request) -> Response:
        partner = self.payer(request)
        with self.billing_call(partner, "status"):
            payer = serialize_billing_response(
                PartnerPayerStatusSerializer, self.billing_manager(request).get_payer(partner)
            )
        return Response(payer)

    @rate_limited("payer_writes")
    def patch(self, request: Request) -> Response:
        partner = self.payer(request)
        if "default_limits_usd" in request.data:
            raise ProvisioningError("invalid_request", DEFAULT_LIMITS_REFUSED_MESSAGE)
        changes = self.validated_body(PartnerPayerUpdateSerializer, request)
        with self.billing_call(partner, "update", fields=changes.keys()):
            payer = serialize_billing_response(
                PartnerPayerStatusSerializer, self.billing_manager(request).update_payer(partner, billing_json(changes))
            )
        return Response(payer)


class PayerWebhookSecretView(PayerAPIView):
    @rate_limited("payer_writes")
    def post(self, request: Request) -> Response:
        partner = self.payer(request)
        with self.billing_call(partner, "webhook_secret"):
            secret = serialize_billing_response(
                PartnerPayerWebhookSecretSerializer, self.billing_manager(request).rotate_payer_webhook_secret(partner)
            )
        return Response(secret, headers={"Cache-Control": "no-store"})


class PayerTestEventView(PayerAPIView):
    # Every test event makes billing deliver a request to the partner's webhook, so the budget is small and
    # does not grow with the partner's tier.
    @rate_limited("payer_test_events", budget=Budget(burst=5, per_hour=30), multipliers=FLAT_MULTIPLIERS)
    def post(self, request: Request) -> Response:
        partner = self.payer(request)
        with self.billing_call(partner, "test_event"):
            event = serialize_billing_response(
                PartnerPayerTestEventSerializer, self.billing_manager(request).send_payer_test_event(partner)
            )
        return Response(event)


class PayerOrganizationsView(PayerAPIView):
    @rate_limited("payer_reads")
    def get(self, request: Request) -> Response:
        partner = self.payer(request)
        page = self.validated_query(PartnerPayerPageQuerySerializer, request)
        with self.billing_call(partner, "organizations"):
            organizations = serialize_billing_response(
                PartnerPayerOrganizationListSerializer,
                self.billing_manager(request).list_payer_organizations(partner, **page),
            )
        return Response(organizations)


class PayerOrganizationLimitsView(PayerAPIView):
    @rate_limited("payer_writes")
    def patch(self, request: Request, organization_id: uuid.UUID) -> Response:
        partner = self.payer(request)
        body = self.validated_body(PartnerPayerOrganizationLimitsSerializer, request)
        with self.billing_call(partner, "organization_limits", fields=body.keys()):
            organization = serialize_billing_response(
                PartnerPayerOrganizationSerializer,
                self.billing_manager(request).update_payer_organization_limits(
                    partner, str(organization_id), body["custom_limits_usd"]
                ),
            )
        return Response(organization)


class PayerInvoicesView(PayerAPIView):
    @rate_limited("payer_reads")
    def get(self, request: Request) -> Response:
        partner = self.payer(request)
        filters = self.validated_query(PartnerPayerInvoicesQuerySerializer, request)
        with self.billing_call(partner, "invoices"):
            invoices = serialize_billing_response(
                PartnerPayerInvoiceListSerializer, self.billing_manager(request).list_payer_invoices(partner, **filters)
            )
        return Response(invoices)


class PayerSettlementsView(PayerAPIView):
    @rate_limited("payer_reads")
    def get(self, request: Request) -> Response:
        partner = self.payer(request)
        page = self.validated_query(PartnerPayerPageQuerySerializer, request)
        with self.billing_call(partner, "settlements"):
            settlements = serialize_billing_response(
                PartnerPayerSettlementListSerializer,
                self.billing_manager(request).list_payer_settlements(partner, **page),
            )
        return Response(settlements)


class PayerSettlementDetailView(PayerAPIView):
    @rate_limited("payer_reads")
    def get(self, request: Request, settlement_id: str) -> Response:
        partner = self.payer(request)
        with self.billing_call(partner, "settlement"):
            settlement = serialize_billing_response(
                PartnerPayerSettlementDetailSerializer,
                self.billing_manager(request).get_payer_settlement(partner, settlement_id),
            )
        return Response(settlement)
