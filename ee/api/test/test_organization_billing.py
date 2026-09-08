import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from unittest.mock import MagicMock, patch

from django.utils import timezone

import jwt
from rest_framework import status

from posthog.models import OrganizationMembership, PersonalAPIKey
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.rate_limit import BillingReadBurstRateThrottle

from ee.api.test.base import APILicensedTest
from ee.billing.grants import BillingEntitlement, entitlements_for

PERIOD_START = int(datetime(2026, 9, 1, tzinfo=UTC).timestamp())
PERIOD_END = int(datetime(2026, 10, 1, tzinfo=UTC).timestamp())

SUBSCRIPTION: dict[str, Any] = {
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

USAGE: dict[str, Any] = {
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

PRODUCTS: dict[str, Any] = {
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
        # The viewset is behind a feature flag; on for the suite, off in the one test about the gate.
        api_flag = patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True)
        self.owner_only = owner_only.start()
        self.member_read = member_read.start()
        self.api_flag = api_flag.start()
        self.addCleanup(owner_only.stop)
        self.addCleanup(member_read.stop)
        self.addCleanup(api_flag.stop)

    def _url(self, path: str) -> str:
        return f"/api/organizations/{self.organization.id}/billing/{path}"

    @patch("ee.billing.billing_manager.requests.get")
    def test_endpoints_are_behind_the_feature_flag(self, mock_get):
        self.api_flag.return_value = False
        response = self.client.get(self._url("subscription/"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_get.assert_not_called()

    @patch("ee.billing.billing_manager.requests.get")
    def test_session_callers_are_throttled_too(self, mock_get):
        mock_get.return_value = _response(SUBSCRIPTION)
        with (
            patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True),
            patch.object(BillingReadBurstRateThrottle, "rate", "1/minute"),
        ):
            first = self.client.get(self._url("subscription/"))
            second = self.client.get(self._url("subscription/"))
        self.assertEqual(
            (first.status_code, second.status_code), (status.HTTP_200_OK, status.HTTP_429_TOO_MANY_REQUESTS)
        )

    @patch("ee.billing.billing_manager.requests.get")
    def test_subscription_is_reshaped_to_the_organization_contract(self, mock_get):
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
        self.assertEqual(claims["entitlements"], entitlements_for(BillingEntitlement.FULL_ACCESS))
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
        # Today's 120 events are added to the product row, as the root billing read does.
        self.assertEqual(body["products"][0]["current_usage"], 3120520)
        self.assertEqual(body["products"][0]["usage_ratio"], 3120520 / 5000000)

    @patch("ee.billing.billing_manager.requests.get")
    def test_member_reads_the_usage_status_and_needs_the_read_flag_for_the_counts(self, mock_get):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.organization.usage = {"recordings": {"usage": 15000, "limit": 15000, "quota_limited_until": PERIOD_END}}
        self.organization.save()
        response = self.client.get(self._url("usage/"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_get.assert_not_called()

        mock_get.return_value = _response(USAGE_STATUS)
        response = self.client.get(self._url("usage/status/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertTrue(mock_get.call_args.args[0].endswith("/api/v2/billing/usage/status/"))
        products = {p["key"]: p for p in response.json()["products"]}
        self.assertEqual(products["session_replay"]["quota_limited_until"], "2026-10-01T00:00:00Z")
        self.assertTrue(products["session_replay"]["has_exceeded_limit"])
        self.assertNotIn("current_usage", products["session_replay"])
        self.assertNotIn("usage_summary", response.json())

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

    def _oauth_token(self, scope: str) -> str:
        app = OAuthApplication.objects.create(
            name="MCP client",
            client_id="test_billing_oauth_client",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            user=self.user,
        )
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=app,
            token="pha_test_billing_access_token",
            scope=scope,
            expires=timezone.now() + timedelta(hours=1),
        )
        self.client.logout()
        return token.token

    @patch("ee.billing.billing_manager.requests.get")
    def test_oauth_token_with_billing_read_reads_like_a_key(self, mock_get):
        # The credential the MCP tools carry: an OAuth access token instead of a personal key.
        mock_get.return_value = _response(SUBSCRIPTION)
        bearer = self._oauth_token("billing:read")
        response = self.client.get(self._url("subscription/"), headers={"authorization": f"Bearer {bearer}"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        claims = jwt.decode(
            mock_get.call_args.kwargs["headers"]["Authorization"].removeprefix("Bearer "),
            options={"verify_signature": False},
        )
        self.assertEqual((claims["scope"], claims["roles"]), ("billing:read", ["owner"]))
        self.assertEqual(claims["entitlements"], entitlements_for(BillingEntitlement.FULL_ACCESS))

    @patch("ee.billing.billing_manager.requests.get")
    def test_oauth_token_without_billing_scope_is_refused_before_billing_is_called(self, mock_get):
        bearer = self._oauth_token("insight:read")
        response = self.client.get(self._url("subscription/"), headers={"authorization": f"Bearer {bearer}"})
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


USAGE_STATUS: dict[str, Any] = {
    "status": "ok",
    "customer_id": 42,
    "billing_period": USAGE["billing_period"],
    "usage_reported_through": "2026-09-14",
    "products": [
        {
            "kind": "product",
            "key": "product_analytics",
            "usage_key": "events",
            "usage_limit": 5000000,
            "has_exceeded_limit": False,
            "approaching_limit": False,
            "addons": [],
        },
        {
            "kind": "product",
            "key": "session_replay",
            "usage_key": "recordings",
            "usage_limit": 15000,
            "has_exceeded_limit": True,
            "approaching_limit": False,
            "addons": [],
        },
    ],
}

SPEND: dict[str, Any] = {
    "status": "ok",
    "customer_id": 42,
    "billing_period": {"current_period_start": PERIOD_START, "current_period_end": PERIOD_END, "interval": "month"},
    "usage_reported_through": "2026-09-14",
    "current_total_amount_usd": "212.40",
    "current_total_amount_usd_after_discount": "169.92",
    "products": [],
}
FORECAST = {**SPEND, "projected_total_amount_usd": "480.00", "computed_at": PERIOD_START}
SERIES: dict[str, Any] = {
    "status": "ok",
    "customer_id": 42,
    "results": [{"id": i, "label": f"s{i}", "data": [1.0], "dates": ["2026-09-01"]} for i in range(3)],
    "team_id_options": [1],
}


class TestOrganizationBillingSpendForecastAndSeries(TestOrganizationBillingAPI):
    @patch("ee.billing.billing_manager.requests.get")
    def test_spend_and_forecast_are_reshaped(self, mock_get):
        mock_get.return_value = _response(SPEND)
        response = self.client.get(self._url("spend/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()
        self.assertEqual(body["current_total_amount_usd"], "212.40")
        self.assertEqual(body["billing_period"]["current_period_end"], "2026-10-01T00:00:00Z")
        self.assertNotIn("status", body)
        mock_get.return_value = _response(FORECAST)
        response = self.client.get(self._url("forecast/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()["computed_at"], "2026-09-01T00:00:00Z")

    @patch("ee.billing.billing_manager.requests.get")
    def test_member_without_the_read_flag_is_refused_spend_before_billing_is_called(self, mock_get):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.get(self._url("spend/"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        response = self.client.get(self._url("forecast/"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_get.assert_not_called()

    @patch("ee.billing.billing_manager.requests.get")
    def test_timeseries_pages_by_cursor_the_way_the_api_does(self, mock_get):
        mock_get.return_value = _response({**SERIES, "next": "c2", "total_count": 7})
        response = self.client.get(self._url("usage/timeseries/?start_date=2026-09-01&end_date=2026-09-14&limit=2"))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()
        sent = mock_get.call_args.kwargs["params"]
        # limit and cursor are the API's names; billing hears page_size and after.
        self.assertEqual((sent.get("page_size"), "limit" in sent), (2, False))
        self.assertEqual((body["count"], body["previous"], len(body["results"])), (7, None, 3))
        self.assertTrue(
            body["next"].endswith(
                "/billing/usage/timeseries/?start_date=2026-09-01&end_date=2026-09-14&limit=2&cursor=c2"
            ),
            body["next"],
        )

        # The second page's previous is the first page: the same request without a cursor.
        mock_get.return_value = _response({**SERIES, "next": "c3", "previous": "", "total_count": 7})
        response = self.client.get(
            self._url("usage/timeseries/?start_date=2026-09-01&end_date=2026-09-14&limit=2&cursor=c2")
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        sent = mock_get.call_args.kwargs["params"]
        self.assertEqual((sent.get("after"), "cursor" in sent), ("c2", False))
        body = response.json()
        self.assertTrue(
            body["previous"].endswith("/billing/usage/timeseries/?start_date=2026-09-01&end_date=2026-09-14&limit=2"),
            body["previous"],
        )

        # Further in, previous carries the cursor that seeks to the page before.
        mock_get.return_value = _response({**SERIES, "previous": "c2", "total_count": 7})
        response = self.client.get(
            self._url("usage/timeseries/?start_date=2026-09-01&end_date=2026-09-14&limit=2&cursor=c3")
        )
        body = response.json()
        self.assertTrue(body["previous"].endswith("&limit=2&cursor=c2"), body["previous"])
        # The last page has no next link.
        self.assertEqual((body["count"], body["next"]), (7, None))

        mock_get.return_value = _response(SERIES)
        response = self.client.get(self._url("usage/timeseries/?start_date=2026-09-01&end_date=2026-09-14"))
        body = response.json()
        # An unpaged answer has no links and counts what it holds.
        self.assertEqual((body["count"], body["next"], body["previous"]), (3, None, None))

    def test_team_scoped_key_is_refused_on_organization_endpoints_like_everywhere_else(self):
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="x",
            secure_value=hash_key_value(raw),
            scopes=["billing:read"],
            scoped_teams=[self.team.id],
        )
        response = self.client.get(
            self._url("spend/timeseries/?start_date=2026-09-01&end_date=2026-09-14"), HTTP_AUTHORIZATION=f"Bearer {raw}"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("scoped projects", response.json()["detail"])

    @patch("ee.billing.billing_manager.requests.get")
    def test_member_series_are_clipped_to_the_teams_they_can_see(self, mock_get):
        mock_get.return_value = _response(SERIES)
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.member_read.return_value = True
        with patch("ee.api.organization_billing.visible_team_ids", return_value=[self.team.id]):
            response = self.client.get(self._url("usage/timeseries/?start_date=2026-09-01&end_date=2026-09-14"))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        sent = mock_get.call_args.kwargs["params"]
        token = mock_get.call_args.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        claims = jwt.decode(token, options={"verify_signature": False})
        # The filter names the projects even when the member sees every one, so a project deleted
        # since its usage was reported is never read; the token itself carries no list.
        self.assertEqual((claims["projects"], sent["team_ids"]), (None, json.dumps([self.team.id])))
        with patch("ee.api.organization_billing.visible_team_ids", return_value=[]):
            response = self.client.get(self._url("usage/timeseries/?start_date=2026-09-01&end_date=2026-09-14"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("ee.billing.billing_manager.requests.get")
    def test_a_whole_organization_caller_may_name_a_project_the_organization_no_longer_has(self, mock_get):
        mock_get.return_value = _response(SERIES)
        response = self.client.get(
            self._url("usage/timeseries/?start_date=2026-09-01&end_date=2026-09-14&team_ids=[999999]")
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(mock_get.call_args.kwargs["params"]["team_ids"], json.dumps([999999]))
        # Below full access the filter is the caller's visible projects, which a deleted one is never in.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.member_read.return_value = True
        with patch("ee.api.organization_billing.visible_team_ids", return_value=[self.team.id]):
            response = self.client.get(
                self._url("usage/timeseries/?start_date=2026-09-01&end_date=2026-09-14&team_ids=[999999]")
            )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("ee.billing.billing_manager.requests.get")
    def test_projects_names_live_projects_and_marks_deleted_ones(self, mock_get):
        mock_get.return_value = _response({"results": [{"id": 424242}, {"id": self.team.id}]})
        response = self.client.get(self._url("projects/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(
            response.json(),
            {
                "count": 2,
                "next": None,
                "previous": None,
                "results": [
                    {"id": self.team.id, "name": self.team.name, "deleted": False},
                    {"id": 424242, "name": None, "deleted": True},
                ],
            },
        )
        self.assertTrue(mock_get.call_args.args[0].endswith("/api/v2/billing/projects/"), mock_get.call_args.args[0])
        # A member's list is the projects they can see, so a deleted project is not offered to them.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.member_read.return_value = True
        with patch("ee.api.organization_billing.visible_team_ids", return_value=[self.team.id]):
            response = self.client.get(self._url("projects/"))
        self.assertEqual([project["id"] for project in response.json()["results"]], [self.team.id])


INVOICES: dict[str, Any] = {
    "status": "ok",
    "customer_id": 42,
    "next": "bz0x",
    "previous": None,
    "results": [
        {
            "id": "in_1",
            "number": "A1-0007",
            "status": "paid",
            "currency": "usd",
            "subtotal": "412.50",
            "total": "330.00",
            "amount_due": "330.00",
            "amount_paid": "330.00",
            "period_start": PERIOD_START,
            "period_end": PERIOD_END,
            "created": PERIOD_START,
            "due_date": None,
        }
    ],
}
LIMITS: dict[str, Any] = {
    "status": "ok",
    "customer_id": 42,
    "results": [
        {
            "key": "product_analytics",
            "limit_usd": 500,
            "next_period_limit_usd": None,
            "spend_usd": "212.40",
            "reached": False,
        }
    ],
}


class TestOrganizationBillingInvoicesAndLimits(TestOrganizationBillingAPI):
    @patch("ee.billing.billing_manager.requests.get")
    def test_invoices_carry_iso_dates_and_cursor_urls(self, mock_get):
        mock_get.return_value = _response(INVOICES)
        response = self.client.get(self._url("invoices/?limit=1&status=paid"))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()
        self.assertEqual(body["results"][0]["period_start"], "2026-09-01T00:00:00Z")
        self.assertIsNone(body["results"][0]["due_date"])
        # The next link keeps the page size and filter of this request.
        self.assertTrue(body["next"].endswith("/billing/invoices/?limit=1&status=paid&cursor=bz0x"), body["next"])
        self.assertIsNone(body["previous"])
        self.assertEqual(mock_get.call_args.kwargs["params"], {"limit": 1, "status": "paid"})
        for query in ("limit=abc", "limit=0", "status=draft"):
            response = self.client.get(self._url(f"invoices/?{query}"))
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, query)

    @patch("ee.api.organization_billing.fetch_invoice_document")
    @patch("ee.billing.billing_manager.requests.get")
    async def test_invoice_content_streams_the_pdf_without_exposing_the_link(self, mock_billing_get, mock_upstream_get):
        mock_billing_get.return_value = _response(
            {"status": "ok", "customer_id": 42, "url": "https://pay.example/in_1/pdf"}
        )
        read_from_provider: list[bytes] = []

        def provider_chunks():
            for chunk in (b"%PDF-1.4", b"..."):
                read_from_provider.append(chunk)
                yield chunk

        upstream = MagicMock()
        upstream.status_code = 200
        upstream.iter_content.return_value = provider_chunks()
        mock_upstream_get.return_value = upstream
        await self.async_client.aforce_login(self.user)

        # The ASGI client, because that is how PostHog serves requests and where a synchronous
        # body is read whole before the first byte goes out.
        response = await self.async_client.get(self._url("invoices/in_1/content/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="in_1.pdf"')
        body = cast(Any, response).streaming_content.__aiter__()
        first = await body.__anext__()
        self.assertEqual((first, read_from_provider), (b"%PDF-1.4", [b"%PDF-1.4"]))
        self.assertEqual(first + b"".join([chunk async for chunk in body]), b"%PDF-1.4...")
        self.assertEqual(mock_upstream_get.call_args.args[0], "https://pay.example/in_1/pdf")
        upstream.close.assert_called_once()

    @patch("ee.api.organization_billing.fetch_invoice_document")
    @patch("ee.billing.billing_manager.requests.get")
    def test_invoice_content_is_a_404_when_the_provider_has_no_document(self, mock_billing_get, mock_upstream_get):
        mock_billing_get.return_value = _response(
            {"status": "ok", "customer_id": 42, "url": "https://pay.example/in_1/pdf"}
        )
        upstream = MagicMock(status_code=404)
        mock_upstream_get.return_value = upstream
        response = self.client.get(self._url("invoices/in_1/content/"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json()["detail"], "No document for invoice in_1.")
        upstream.iter_content.assert_not_called()
        upstream.close.assert_called_once()

    @patch("ee.billing.billing_manager.requests.get")
    def test_limits_pass_through(self, mock_get):
        mock_get.return_value = _response(LIMITS)
        response = self.client.get(self._url("limits/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()["results"][0]["reached"], False)

    @patch("ee.billing.billing_manager.requests.get")
    def test_admin_under_owner_only_billing_is_refused_invoices_and_limits(self, mock_get):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.owner_only.return_value = True
        for path in ("invoices/", "limits/", "invoices/in_1/content/"):
            response = self.client.get(self._url(path))
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, path)
        mock_get.assert_not_called()
