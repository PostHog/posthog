from datetime import UTC, datetime

from unittest.mock import MagicMock, patch

import jwt
from rest_framework import status

from posthog.models import OrganizationMembership, PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from ee.api.test.base import APILicensedTest

PERIOD_START = int(datetime(2026, 9, 1, tzinfo=UTC).timestamp())
PERIOD_END = int(datetime(2026, 10, 1, tzinfo=UTC).timestamp())

SUBSCRIPTION = {
    "status": "ok",
    "customer_id": 42,
    "has_subscription": True,
    "billing_period": {"current_period_start": PERIOD_START, "current_period_end": PERIOD_END, "interval": "month"},
    "free_trial": {"active": False, "expires_at": None},
    "provider_customer_id": "cus_Q1x9v2AbCdEf",
    "has_active_subscription": True,
    "subscription_level": "paid",
    "billing_plan": "boost",
    "billing_provider": "posthog",
    "deactivated": False,
    "is_annual_plan_customer": False,
    "trial": {"id": 7, "type": "standard", "status": "active", "target": "paid", "expires_at": PERIOD_END},
    "discount_percent": 20,
    "discount_amount_usd": None,
    "amount_off_expires_at": None,
    "startup_program_label": "Startup",
    "startup_program_label_previous": None,
}

USAGE = {
    "status": "ok",
    "customer_id": 42,
    "billing_period": {"current_period_start": PERIOD_START, "current_period_end": PERIOD_END, "interval": "month"},
    "usage_reported_through": "2026-09-14",
    "usage_summary": [
        {"usage_key": "events", "usage": 3120400, "limit": 5000000},
        {"usage_key": "recordings", "usage": 15000, "limit": 15000},
    ],
    "products": [
        {
            "kind": "product",
            "key": "product_analytics",
            "usage_key": "events",
            "current_usage": 3120400,
            "usage_limit": 5000000,
            "has_exceeded_limit": False,
            "usage_ratio": 0.62,
            "tier_usage": [{"up_to": 1000000, "current_usage": 1000000}],
            "addons": [],
        }
    ],
}

PRODUCTS = {
    "status": "ok",
    "customer_id": 42,
    "products": [{"kind": "product", "key": "product_analytics", "name": "Product analytics", "addons": []}],
}


def _response(payload: dict, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


class TestOrganizationBillingAPI(APILicensedTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()
        owner_only = patch("ee.billing.grants._owner_only_billing_enabled", return_value=False)
        member_read = patch("ee.billing.grants._member_billing_usage_spend_read_access_enabled", return_value=False)
        self.owner_only = owner_only.start()
        self.member_read = member_read.start()
        self.addCleanup(owner_only.stop)
        self.addCleanup(member_read.stop)

    def _url(self, path: str) -> str:
        return f"/api/organizations/{self.organization.id}/billing/{path}"

    @patch("ee.billing.billing_manager.requests.get")
    def test_subscription_is_reshaped_to_the_public_contract(self, mock_get):
        mock_get.return_value = _response(SUBSCRIPTION)
        response = self.client.get(self._url("subscription/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()
        self.assertNotIn("status", body)
        self.assertEqual(body["customer_id"], "cus_Q1x9v2AbCdEf")
        self.assertEqual(body["billing_provider"], "stripe")
        self.assertEqual(body["billing_period"]["current_period_start"], "2026-09-01T00:00:00Z")
        self.assertEqual(body["trial"]["expires_at"], "2026-10-01T00:00:00Z")
        self.assertNotIn("id", body["trial"])
        self.assertIsNone(body["free_trial_until"])
        self.assertTrue(body["billing_portal_url"].endswith("/api/billing/portal"))
        self.assertEqual(body["license"]["plan"], self.license.plan)
        self.assertNotIn("invoices_url", body)
        called_url = mock_get.call_args.args[0]
        self.assertTrue(called_url.endswith("/api/v2/billing/subscription/"), called_url)

    @patch("ee.billing.billing_manager.requests.get")
    def test_the_call_to_billing_carries_a_minted_token_with_the_grants(self, mock_get):
        mock_get.return_value = _response(SUBSCRIPTION)
        self.client.get(self._url("subscription/"))
        token = mock_get.call_args.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        self.assertEqual(jwt.get_unverified_header(token)["typ"], "at+jwt")
        claims = jwt.decode(token, options={"verify_signature": False})
        self.assertEqual(claims["scope"], "billing:read")
        self.assertEqual(claims["roles"], ["owner"])
        self.assertEqual(claims["entitlements"], ["billing:full_access"])
        self.assertEqual(claims["org_id"], str(self.organization.id))
        self.assertIsNone(claims["projects"])

    @patch("ee.billing.billing_manager.requests.get")
    def test_current_alias_resolves_the_organization(self, mock_get):
        mock_get.return_value = _response(SUBSCRIPTION)
        response = self.client.get("/api/organizations/@current/billing/subscription/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

    @patch("ee.billing.billing_manager.requests.get")
    def test_usage_merges_todays_usage_and_the_quota_state(self, mock_get):
        mock_get.return_value = _response(USAGE)
        self.organization.usage = {
            "events": {"usage": 3120400, "limit": 5000000, "todays_usage": 120, "quota_limited_until": None},
            "recordings": {"usage": 15000, "limit": 15000, "todays_usage": 0, "quota_limited_until": PERIOD_END},
        }
        self.organization.save()
        response = self.client.get(self._url("usage/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()
        rows = {row["usage_key"]: row for row in body["usage_summary"]}
        self.assertEqual(rows["events"]["todays_usage"], 120)
        self.assertIsNone(rows["events"]["quota_limited_until"])
        self.assertEqual(rows["recordings"]["quota_limited_until"], "2026-10-01T00:00:00Z")
        self.assertEqual(body["usage_reported_through"], "2026-09-14")
        self.assertEqual(body["products"][0]["usage_ratio"], 0.62)

    @patch("ee.billing.billing_manager.requests.get")
    def test_products_and_one_product(self, mock_get):
        mock_get.return_value = _response(PRODUCTS)
        response = self.client.get(self._url("products/?include_plans=true"))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()["results"][0]["key"], "product_analytics")
        self.assertEqual(mock_get.call_args.kwargs["params"], {"include_plans": "true"})

        mock_get.return_value = _response({"status": "ok", "customer_id": 42, "product": PRODUCTS["products"][0]})
        response = self.client.get(self._url("products/product_analytics/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()["key"], "product_analytics")
        self.assertTrue(mock_get.call_args.args[0].endswith("/api/v2/billing/products/product_analytics/"))

    @patch("ee.billing.billing_manager.requests.get")
    def test_billings_refusals_come_back_as_the_matching_errors(self, mock_get):
        mock_get.return_value = _response({"detail": "No product time_travel."}, 404)
        response = self.client.get(self._url("products/time_travel/"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        mock_get.return_value = _response({"detail": "This resource needs the billing:full_access entitlement."}, 403)
        response = self.client.get(self._url("usage/"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("ee.billing.billing_manager.requests.get")
    def test_key_without_billing_scope_is_refused_before_billing_is_called(self, mock_get):
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user, label="x", secure_value=hash_key_value(raw), scopes=["insight:read"]
        )
        response = self.client.get(self._url("subscription/"), HTTP_AUTHORIZATION=f"Bearer {raw}")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_get.assert_not_called()

    @patch("ee.billing.billing_manager.requests.get")
    def test_key_with_billing_read_reads_subscription(self, mock_get):
        mock_get.return_value = _response(SUBSCRIPTION)
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user, label="x", secure_value=hash_key_value(raw), scopes=["billing:read"]
        )
        response = self.client.get(self._url("subscription/"), HTTP_AUTHORIZATION=f"Bearer {raw}")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

    @patch("ee.billing.billing_manager.requests.get")
    def test_non_member_is_refused(self, mock_get):
        self.organization_membership.delete()
        response = self.client.get(self._url("subscription/"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_get.assert_not_called()
