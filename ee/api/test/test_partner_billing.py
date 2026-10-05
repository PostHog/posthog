from typing import Any

from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import SimpleTestCase

import requests
from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, OrganizationMembership
from posthog.models.oauth import OAuthApplication
from posthog.models.oauth_provisioning import ProvisioningConfig

from ee.api.partner_billing import PartnerPayerPortalRequestSerializer, classify_partner_billing_error
from ee.api.test.base import APILicensedTest
from ee.billing.billing_manager import BillingServiceResponseError
from ee.settings import BILLING_SERVICE_URL

CUSTOMER_ORGANIZATION_ID = "0192d7c4-5b6e-7000-8000-00000000c001"
BILLING_DETAIL = "billing-only detail"

PAYER_STATUS: dict[str, Any] = {
    "name": "Example Partner Inc.",
    "billing_enabled": True,
    "has_payment_method": True,
    "billing_details": {
        "address": {
            "line1": "1 Example Street",
            "line2": None,
            "city": "Springfield",
            "state": "CA",
            "postal_code": "00000",
            "country": "US",
        },
        "tax_ids": [{"type": "us_ein", "value": "00-0000000"}],
    },
    "organization_count": 2,
    "webhook": {"url": "https://hooks.example.com/posthog", "secret_created_at": "2026-09-01T00:00:00Z"},
    "past_due": False,
    "spend": {"month_to_date_usd": "1200.50", "alert_usd": "1000.00", "cap_usd": "5000.00", "capped": False},
    "default_limits_usd": {"product_analytics": 500},
}
# Billing can return fields the contract does not name. None of them may reach the caller.
PAYER_STATUS_FROM_BILLING: dict[str, Any] = {**PAYER_STATUS, "stripe_customer_id": "cus_example"}

ORGANIZATION_ROW: dict[str, Any] = {
    "organization_id": CUSTOMER_ORGANIZATION_ID,
    "name": "Example Customer",
    "linked_at": "2026-08-01T00:00:00Z",
    "detached_at": None,
    "custom_limits_usd": {"session_replay": 100},
}
INVOICE: dict[str, Any] = {
    "invoice_id": "in_example1",
    "organization_id": CUSTOMER_ORGANIZATION_ID,
    "period_start": "2026-09-01T00:00:00Z",
    "period_end": "2026-10-01T00:00:00Z",
    "amount_cents": 125000,
    "currency": "usd",
    "status": "paid",
    "settlement_id": "stl_example1",
    "pdf_url": "https://files.example.com/in_example1.pdf",
}
SETTLEMENT: dict[str, Any] = {
    "settlement_id": "stl_example1",
    "period_start": "2026-09-01T00:00:00Z",
    "period_end": "2026-10-01T00:00:00Z",
    "amount_cents": 125000,
    "currency": "usd",
    "status": "paid",
    "attempt_count": 1,
    "next_attempt_at": None,
    "paid_at": "2026-10-02T00:00:00Z",
}


def billing_response(payload: Any, status_code: int = 200) -> MagicMock:
    response = MagicMock(status_code=status_code, text="")
    response.json.return_value = payload
    return response


def create_partner_application(
    organization: Organization | None, client_id: str, *, pays_for_customers: bool = True
) -> OAuthApplication:
    return OAuthApplication.objects.create(
        name=f"Partner {client_id}",
        client_id=client_id,
        client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
        jwks_uri="https://partner.example.com/.well-known/jwks.json",
        authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
        redirect_uris="https://partner.example.com/callback",
        algorithm="RS256",
        organization=organization,
        is_provisioning_partner=True,
        _provisioning_config=ProvisioningConfig(active=True, pays_for_customers=pays_for_customers).model_dump(
            mode="json"
        ),
    )


class TestClassifyPartnerBillingError(SimpleTestCase):
    @parameterized.expand(
        [
            ("missing", BillingServiceResponseError(404, {"detail": BILLING_DETAIL}), (), (404, "not_found", None)),
            (
                "another organization manages the payer",
                BillingServiceResponseError(403, {"detail": BILLING_DETAIL}),
                (),
                (403, "forbidden", None),
            ),
            ("busy", BillingServiceResponseError(409, {"detail": BILLING_DETAIL}), (), (409, "conflict", None)),
            (
                "a field the caller sent",
                BillingServiceResponseError(400, {"attr": "webhook_url", "detail": BILLING_DETAIL}),
                ("webhook_url",),
                (400, "invalid_input", "webhook_url"),
            ),
            (
                "a nested field the caller sent",
                BillingServiceResponseError(400, {"attr": "custom_limits_usd__session_replay"}),
                ("custom_limits_usd",),
                (400, "invalid_input", "custom_limits_usd"),
            ),
            (
                "a field the caller did not send",
                BillingServiceResponseError(400, {"attr": "default_limits_usd", "detail": BILLING_DETAIL}),
                ("webhook_url",),
                (400, "billing_rejected", None),
            ),
            (
                "a body that is not JSON",
                BillingServiceResponseError(400, "Bad Request"),
                (),
                (400, "billing_rejected", None),
            ),
            (
                "token refused",
                BillingServiceResponseError(401, {"detail": BILLING_DETAIL}),
                (),
                (502, "billing_unavailable", None),
            ),
            ("billing failed", BillingServiceResponseError(503, ""), (), (502, "billing_unavailable", None)),
            ("billing unreachable", requests.ConnectionError(), (), (502, "billing_unavailable", None)),
        ]
    )
    def test_answers_in_posthog_terms(self, _name, error, fields, expected):
        refusal = classify_partner_billing_error(error, fields)

        assert (refusal.status, refusal.code, refusal.field) == expected
        assert BILLING_DETAIL not in refusal.message


class TestPartnerPayerPortalRequestSerializer(SimpleTestCase):
    # The return URL is SITE_URL followed by the path, so these would move the browser to another host.
    @parameterized.expand([("a host suffix", ".attacker.example.com/"), ("user info", "@attacker.example.com/")])
    def test_refuses_a_return_path_that_leaves_this_site(self, _name, return_path):
        assert not PartnerPayerPortalRequestSerializer(data={"return_path": return_path}).is_valid()


class TestPartnerBillingAPI(APILicensedTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.application = create_partner_application(self.organization, "example-partner")

    def _url(self, path: str = "", application: OAuthApplication | None = None) -> str:
        application = application or self.application
        return f"/api/organizations/{self.organization.id}/partner_billing/{application.id}/{path}"

    def test_lists_the_paying_partners_this_organization_owns(self):
        create_partner_application(self.organization, "non-paying-partner", pays_for_customers=False)
        create_partner_application(Organization.objects.create(name="Other partner"), "other-partner")

        response = self.client.get(f"/api/organizations/{self.organization.id}/partner_billing/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == [
            {"id": str(self.application.id), "name": "Partner example-partner", "logo_uri": None}
        ]

    def test_refuses_members_below_admin(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        with patch("ee.billing.billing_manager.http_session.request") as request:
            response = self.client.get(self._url())

        assert response.status_code == status.HTTP_403_FORBIDDEN
        request.assert_not_called()

    @parameterized.expand([("owned by another organization", True), ("not paying for customers", False)])
    def test_refuses_partners_this_organization_does_not_manage(self, _name, owned_elsewhere):
        if owned_elsewhere:
            application = create_partner_application(Organization.objects.create(name="Other partner"), "other")
        else:
            application = create_partner_application(self.organization, "non-paying", pays_for_customers=False)

        with patch("ee.billing.billing_manager.http_session.request") as request:
            response = self.client.get(self._url(application=application))

        assert response.status_code == status.HTTP_404_NOT_FOUND
        request.assert_not_called()

    @parameterized.expand(
        [
            ("status", "get", "", None, PAYER_STATUS_FROM_BILLING, ("GET", "/api/payer", None, None), PAYER_STATUS),
            (
                "update",
                "patch",
                "",
                {"spend_cap_usd": "5000", "default_limits_usd": {"product_analytics": 500}},
                PAYER_STATUS_FROM_BILLING,
                (
                    "PATCH",
                    "/api/payer",
                    None,
                    {"spend_cap_usd": "5000.00", "default_limits_usd": {"product_analytics": 500}},
                ),
                PAYER_STATUS,
            ),
            (
                "portal",
                "post",
                "portal/",
                {"return_path": "/organization/billing/partner"},
                {"url": "https://billing.example.com/session/1"},
                (
                    "POST",
                    "/api/payer/portal",
                    None,
                    {"return_url": f"{settings.SITE_URL}/organization/billing/partner"},
                ),
                {"url": "https://billing.example.com/session/1"},
            ),
            (
                "webhook secret",
                "post",
                "webhook_secret/",
                None,
                {"secret": "whsec_ZXhhbXBsZQ==", "created_at": "2026-10-05T12:00:00Z"},
                ("POST", "/api/payer/webhook_secret", None, None),
                {"secret": "whsec_ZXhhbXBsZQ==", "created_at": "2026-10-05T12:00:00Z"},
            ),
            (
                "test event",
                "post",
                "test_event/",
                None,
                {"event_id": "evt_example1"},
                ("POST", "/api/payer/test_event", None, None),
                {"event_id": "evt_example1"},
            ),
            (
                "organizations",
                "get",
                "organizations/?limit=20&offset=40",
                None,
                {"count": 41, "results": [ORGANIZATION_ROW]},
                ("GET", "/api/payer/organizations", {"limit": 20, "offset": 40}, None),
                {"count": 41, "results": [ORGANIZATION_ROW]},
            ),
            (
                "organization limits",
                "patch",
                f"organizations/{CUSTOMER_ORGANIZATION_ID}/limits/",
                {"custom_limits_usd": {"session_replay": 100, "surveys": None}},
                ORGANIZATION_ROW,
                (
                    "PATCH",
                    f"/api/payer/organizations/{CUSTOMER_ORGANIZATION_ID}/limits",
                    None,
                    {"custom_limits_usd": {"session_replay": 100, "surveys": None}},
                ),
                ORGANIZATION_ROW,
            ),
            (
                "invoices",
                "get",
                f"invoices/?organization_id={CUSTOMER_ORGANIZATION_ID}&status=paid",
                None,
                {"count": 1, "results": [INVOICE]},
                ("GET", "/api/payer/invoices", {"organization_id": CUSTOMER_ORGANIZATION_ID, "status": "paid"}, None),
                {"count": 1, "results": [INVOICE]},
            ),
            (
                "settlements",
                "get",
                "settlements/",
                None,
                {"count": 1, "results": [SETTLEMENT]},
                ("GET", "/api/payer/settlements", {}, None),
                {"count": 1, "results": [SETTLEMENT]},
            ),
            (
                "settlement",
                "get",
                "settlements/stl_example1/",
                None,
                {**SETTLEMENT, "invoices": [INVOICE]},
                ("GET", "/api/payer/settlements/stl_example1", None, None),
                {**SETTLEMENT, "invoices": [INVOICE]},
            ),
            (
                "settlement retry",
                "post",
                "settlements/stl_example1/retry/",
                None,
                SETTLEMENT,
                ("POST", "/api/payer/settlements/stl_example1/retry", None, None),
                SETTLEMENT,
            ),
        ]
    )
    def test_serves_each_route_from_billing(
        self, _name, method, path, body, billing_payload, expected_request, expected_response
    ):
        with patch(
            "ee.billing.billing_manager.http_session.request", return_value=billing_response(billing_payload)
        ) as request:
            response = getattr(self.client, method)(self._url(path), body, format="json")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == expected_response
        expected_method, expected_path, expected_params, expected_body = expected_request
        assert request.call_args.args == (expected_method, f"{BILLING_SERVICE_URL}{expected_path}")
        assert request.call_args.kwargs["params"] == expected_params
        assert request.call_args.kwargs["json"] == expected_body

    @parameterized.expand(
        [
            (
                "billing rejects a field the caller sent",
                billing_response({"type": "validation_error", "attr": "webhook_url", "detail": BILLING_DETAIL}, 400),
                status.HTTP_400_BAD_REQUEST,
                {"code": "invalid_input", "attr": "webhook_url"},
            ),
            (
                "another organization manages the payer",
                billing_response({"detail": BILLING_DETAIL}, 403),
                status.HTTP_403_FORBIDDEN,
                {"code": "forbidden", "attr": None},
            ),
            (
                "billing unreachable",
                requests.ConnectionError(BILLING_DETAIL),
                status.HTTP_502_BAD_GATEWAY,
                {"code": "billing_unavailable", "attr": None},
            ),
        ]
    )
    def test_answers_billing_refusals_in_posthog_terms(self, _name, outcome, expected_status, expected_error):
        side_effect = outcome if isinstance(outcome, Exception) else [outcome]
        with patch("ee.billing.billing_manager.http_session.request", side_effect=side_effect):
            response = self.client.patch(
                self._url(), {"webhook_url": "https://hooks.example.com/posthog"}, format="json"
            )

        assert response.status_code == expected_status
        assert {key: response.json()[key] for key in expected_error} == expected_error
        assert BILLING_DETAIL not in response.content.decode()
