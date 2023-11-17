from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch
from uuid import uuid4

import jwt
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from freezegun import freeze_time
from rest_framework import status

from ee.api.test.base import APILicensedTest
from ee.billing.billing_types import BillingPeriod, CustomerInfo, CustomerProduct
from ee.models.license import License
from posthog.cloud_utils import (
    TEST_clear_instance_license_cache,
    get_cached_instance_license,
)
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.test.base import APIBaseTest, _create_event, flush_persons_and_events


def create_billing_response(**kwargs) -> Dict[str, Any]:
    data: Any = {"license": {"type": "cloud"}}
    data.update(kwargs)
    return data


def create_missing_billing_customer(**kwargs) -> CustomerInfo:
    data = CustomerInfo(
        customer_id="cus_123",
        deactivated=False,
        custom_limits_usd={},
        has_active_subscription=False,
        current_total_amount_usd="0.00",
        products=None,
        billing_period=BillingPeriod(
            current_period_start="2022-10-07T11:12:48",
            current_period_end="2022-11-07T11:12:48",
        ),
        usage_summary={
            "events": {"limit": None, "usage": 0},
            "recordings": {"limit": None, "usage": 0},
            "rows_synced": {"limit": None, "usage": 0},
        },
        free_trial_until=None,
        available_features=[],
    )
    data.update(kwargs)
    return data


def create_billing_customer(**kwargs) -> CustomerInfo:
    data = CustomerInfo(
        customer_id="cus_123",
        custom_limits_usd={},
        has_active_subscription=True,
        current_total_amount_usd="100.00",
        deactivated=False,
        products=[
            CustomerProduct(
                name="Product OS",
                description="Product Analytics, event pipelines, data warehousing",
                price_description=None,
                type="events",
                image_url="https://posthog.com/static/images/product-os.png",
                free_allocation=10000,
                tiers=[
                    {
                        "unit_amount_usd": "0.00",
                        "up_to": 1000000,
                        "current_amount_usd": "0.00",
                    },
                    {
                        "unit_amount_usd": "0.00045",
                        "up_to": 2000000,
                        "current_amount_usd": None,
                    },
                ],
                tiered=True,
                unit_amount_usd="0.00",
                current_amount_usd="0.00",
                current_usage=0,
                usage_limit=None,
                has_exceeded_limit=False,
                percentage_usage=0,
                projected_usage=0,
                projected_amount_usd="0.00",
            )
        ],
        billing_period=BillingPeriod(
            current_period_start="2022-10-07T11:12:48",
            current_period_end="2022-11-07T11:12:48",
        ),
        usage_summary={
            "events": {"limit": None, "usage": 0},
            "recordings": {"limit": None, "usage": 0},
            "rows_synced": {"limit": None, "usage": 0},
        },
        free_trial_until=None,
    )
    data.update(kwargs)
    return data


def create_billing_products_response(**kwargs) -> Dict[str, List[CustomerProduct]]:
    data: Any = {
        "products": [
            CustomerProduct(
                name="Product OS",
                description="Product Analytics, event pipelines, data warehousing",
                price_description=None,
                type="events",
                image_url="https://posthog.com/static/images/product-os.png",
                free_allocation=10000,
                tiers=[
                    {
                        "unit_amount_usd": "0.00",
                        "up_to": 1000000,
                        "current_amount_usd": "0.00",
                    },
                    {
                        "unit_amount_usd": "0.00045",
                        "up_to": 2000000,
                        "current_amount_usd": None,
                    },
                ],
                tiered=True,
                unit_amount_usd="0.00",
                current_amount_usd="0.00",
                current_usage=0,
                usage_limit=None,
                has_exceeded_limit=False,
                percentage_usage=0,
                projected_usage=0,
                projected_amount_usd="0.00",
            )
        ]
    }
    data.update(kwargs)
    return data


class TestUnlicensedBillingAPI(APIBaseTest):
    @patch("ee.api.billing.requests.get")
    @freeze_time("2022-01-01")
    def test_billing_v2_calls_the_service_without_token(self, mock_request):
        def mock_implementation(url: str, headers: Any = None, params: Any = None) -> MagicMock:
            mock = MagicMock()
            mock.status_code = 404

            if "api/billing/portal" in url:
                mock.status_code = 200
                mock.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}
            elif "api/billing" in url:
                mock.status_code = 401
                mock.json.return_value = {"detail": "Authorization is missing."}
            elif "api/products" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_products_response()

            return mock

        mock_request.side_effect = mock_implementation

        TEST_clear_instance_license_cache()
        res = self.client.get("/api/billing-v2")
        assert res.status_code == 200
        assert res.json() == {
            "available_features": [],
            "products": create_billing_products_response()["products"],
        }


class TestBillingAPI(APILicensedTest):
    def test_billing_v2_fails_for_old_license_type(self):
        self.license.key = "test_key"
        self.license.save()
        TEST_clear_instance_license_cache()

        res = self.client.get("/api/billing-v2")
        assert res.status_code == 404
        assert res.json()["detail"] == "Billing V2 is not supported for this license type"

    @patch("ee.api.billing.requests.get")
    @freeze_time("2022-01-01")
    def test_billing_v2_calls_the_service_with_appropriate_token(self, mock_request):
        def mock_implementation(url: str, headers: Any = None, params: Any = None) -> MagicMock:
            mock = MagicMock()
            mock.status_code = 404

            if "api/billing/portal" in url:
                mock.status_code = 200
                mock.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}
            elif "api/billing" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_response(customer=create_billing_customer())

            return mock

        mock_request.side_effect = mock_implementation

        TEST_clear_instance_license_cache()

        self.client.get("/api/billing-v2")
        assert mock_request.call_args_list[0].args[0].endswith("/api/billing")
        token = mock_request.call_args_list[0].kwargs["headers"]["Authorization"].split(" ")[1]

        secret = self.license.key.split("::")[1]

        decoded_token = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience="posthog:license-key",
            options={"verify_aud": True},
        )

        assert decoded_token == {
            "aud": "posthog:license-key",
            "exp": 1640996100,
            "id": self.license.key.split("::")[0],
            "organization_id": str(self.organization.id),
            "organization_name": "Test",
        }

    @patch("ee.api.billing.requests.get")
    def test_billing_v2_returns_if_billing_exists(self, mock_request):
        def mock_implementation(url: str, headers: Any = None, params: Any = None) -> MagicMock:
            mock = MagicMock()
            mock.status_code = 404

            if "api/billing/portal" in url:
                mock.status_code = 200
                mock.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}
            elif "api/billing" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_response(customer=create_billing_customer())

            return mock

        mock_request.side_effect = mock_implementation

        TEST_clear_instance_license_cache()
        response = self.client.get("/api/billing-v2")
        assert response.status_code == status.HTTP_200_OK

        assert response.json() == {
            "customer_id": "cus_123",
            "license": {"plan": "cloud"},
            "custom_limits_usd": {},
            "has_active_subscription": True,
            "stripe_portal_url": "https://billing.stripe.com/p/session/test_1234",
            "current_total_amount_usd": "100.00",
            "available_features": [],
            "deactivated": False,
            "products": [
                {
                    "name": "Product OS",
                    "description": "Product Analytics, event pipelines, data warehousing",
                    "price_description": None,
                    "type": "events",
                    "image_url": "https://posthog.com/static/images/product-os.png",
                    "free_allocation": 10000,
                    "tiers": [
                        {
                            "unit_amount_usd": "0.00",
                            "up_to": 1000000,
                            "current_amount_usd": "0.00",
                        },
                        {
                            "unit_amount_usd": "0.00045",
                            "up_to": 2000000,
                            "current_amount_usd": None,
                        },
                    ],
                    "tiered": True,
                    "current_amount_usd": "0.00",
                    "current_usage": 0,
                    "usage_limit": None,
                    "percentage_usage": 0,
                    "has_exceeded_limit": False,
                    "unit_amount_usd": "0.00",
                    "projected_amount_usd": "0.00",
                    "projected_usage": 0,
                }
            ],
            "billing_period": {
                "current_period_start": "2022-10-07T11:12:48",
                "current_period_end": "2022-11-07T11:12:48",
            },
            "usage_summary": {
                "events": {"limit": None, "usage": 0},
                "recordings": {"limit": None, "usage": 0},
                "rows_synced": {"limit": None, "usage": 0},
            },
            "free_trial_until": None,
        }

    @patch("ee.api.billing.requests.get")
    def test_billing_v2_returns_if_doesnt_exist(self, mock_request):
        def mock_implementation(url: str, headers: Any = None, params: Any = None) -> MagicMock:
            mock = MagicMock()
            mock.status_code = 404

            if "api/billing/portal" in url:
                mock.status_code = 200
                mock.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}
            elif "api/billing" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_response(customer=create_missing_billing_customer())
            elif "api/products" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_products_response()

            return mock

        mock_request.side_effect = mock_implementation

        response = self.client.get("/api/billing-v2")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "customer_id": "cus_123",
            "license": {"plan": "cloud"},
            "custom_limits_usd": {},
            "has_active_subscription": False,
            "available_features": [],
            "products": [
                {
                    "name": "Product OS",
                    "description": "Product Analytics, event pipelines, data warehousing",
                    "price_description": None,
                    "type": "events",
                    "free_allocation": 10000,
                    "tiers": [
                        {
                            "unit_amount_usd": "0.00",
                            "up_to": 1000000,
                            "current_amount_usd": "0.00",
                        },
                        {
                            "unit_amount_usd": "0.00045",
                            "up_to": 2000000,
                            "current_amount_usd": None,
                        },
                    ],
                    "current_usage": 0,
                    "percentage_usage": 0.0,
                    "current_amount_usd": "0.00",
                    "has_exceeded_limit": False,
                    "projected_amount_usd": "0.00",
                    "projected_usage": 0,
                    "tiered": True,
                    "unit_amount_usd": "0.00",
                    "usage_limit": None,
                    "image_url": "https://posthog.com/static/images/product-os.png",
                    "percentage_usage": 0.0,
                }
            ],
            "billing_period": {
                "current_period_start": "2022-10-07T11:12:48",
                "current_period_end": "2022-11-07T11:12:48",
            },
            "usage_summary": {
                "events": {"limit": None, "usage": 0},
                "recordings": {"limit": None, "usage": 0},
                "rows_synced": {"limit": None, "usage": 0},
            },
            "free_trial_until": None,
            "current_total_amount_usd": "0.00",
            "deactivated": False,
            "stripe_portal_url": "https://billing.stripe.com/p/session/test_1234",
        }

    @patch("ee.api.billing.requests.get")
    def test_billing_stores_valid_license(self, mock_request):
        self.license.delete()

        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {
            "license": {
                "type": "scale",
            }
        }
        response = self.client.patch(
            "/api/billing-v2/license",
            {
                "license": "test::test",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"success": True}
        license = License.objects.first_valid()
        assert license
        assert license.key == "test::test"
        assert license.plan == "scale"

    @patch("ee.api.billing.requests.get")
    def test_billing_ignores_invalid_license(self, mock_request):
        self.license.delete()

        mock_request.return_value.status_code = 403
        mock_request.return_value.json.return_value = {}
        response = self.client.patch(
            "/api/billing-v2/license",
            {
                "license": "test::test",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "attr": "license",
            "code": "invalid_input",
            "detail": "License could not be activated. Please contact support. (BillingService status 403)",
            "type": "validation_error",
        }

    @freeze_time("2022-01-01T12:00:00Z")
    @patch("ee.api.billing.requests.get")
    def test_license_is_updated_on_billing_load(self, mock_request):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {
            "license": {
                "type": "scale",
            },
            "customer": create_billing_customer(),
        }

        assert self.license.plan == "enterprise"
        self.client.get("/api/billing-v2")
        self.license.refresh_from_db()

        self.license.valid_until = datetime(2022, 1, 2, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
        self.license.save()
        assert self.license.plan == "scale"
        TEST_clear_instance_license_cache()
        license = get_cached_instance_license()
        assert license.plan == "scale"
        assert license.valid_until == datetime(2022, 1, 2, 0, 0, 0, tzinfo=ZoneInfo("UTC"))

        mock_request.return_value.json.return_value = {
            "license": {
                "type": "enterprise",
            },
            "customer": create_billing_customer(),
        }

        self.client.get("/api/billing-v2")
        license = get_cached_instance_license()
        assert license.plan == "enterprise"
        # Should be extended by 30 days
        assert license.valid_until == datetime(2022, 1, 31, 12, 0, 0, tzinfo=ZoneInfo("UTC"))

    @patch("ee.api.billing.requests.get")
    def test_organization_available_features_updated_if_different(self, mock_request):
        def mock_implementation(url: str, headers: Any = None, params: Any = None) -> MagicMock:
            mock = MagicMock()
            mock.status_code = 404

            if "api/billing/portal" in url:
                mock.status_code = 200
                mock.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}
            elif "api/billing" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_response(
                    customer=create_billing_customer(available_features=["feature1", "feature2"])
                )

            return mock

        mock_request.side_effect = mock_implementation

        self.organization.available_features = []
        self.organization.save()

        assert self.organization.available_features == []
        self.client.get("/api/billing-v2")
        self.organization.refresh_from_db()
        assert self.organization.available_features == ["feature1", "feature2"]

    @patch("ee.api.billing.requests.get")
    def test_organization_usage_update(self, mock_request):
        self.organization.customer_id = None
        self.organization.usage = None
        self.organization.save()

        def mock_implementation(url: str, headers: Any = None, params: Any = None) -> MagicMock:
            mock = MagicMock()
            mock.status_code = 404

            if "api/billing/portal" in url:
                mock.status_code = 200
                mock.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}
            elif "api/billing" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_response(
                    customer=create_billing_customer(has_active_subscription=True)
                )
                mock.json.return_value["customer"]["usage_summary"]["events"]["usage"] = 1000

            elif "api/products" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_products_response()

            return mock

        mock_request.side_effect = mock_implementation

        assert not self.organization.usage
        res = self.client.get("/api/billing-v2")
        assert res.status_code == 200
        self.organization.refresh_from_db()
        assert self.organization.usage == {
            "events": {
                "limit": None,
                "todays_usage": 0,
                "usage": 1000,
            },
            "recordings": {
                "limit": None,
                "todays_usage": 0,
                "usage": 0,
            },
            "rows_synced": {
                "limit": None,
                "todays_usage": 0,
                "usage": 0,
            },
            "period": ["2022-10-07T11:12:48", "2022-11-07T11:12:48"],
        }

        def mock_implementation_missing_customer(url: str, headers: Any = None, params: Any = None) -> MagicMock:
            mock = MagicMock()
            mock.status_code = 404

            if "api/billing/portal" in url:
                mock.status_code = 200
                mock.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}
            elif "api/billing" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_response(customer=create_missing_billing_customer())
            elif "api/products" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_products_response()

            return mock

        mock_request.side_effect = mock_implementation_missing_customer

        # Test unsubscribed config
        res = self.client.get("/api/billing-v2")
        self.organization.refresh_from_db()
        assert self.organization.usage == {
            "events": {
                "limit": None,
                "todays_usage": 0,
                "usage": 0,
            },
            "recordings": {
                "limit": None,
                "todays_usage": 0,
                "usage": 0,
            },
            "rows_synced": {
                "limit": None,
                "todays_usage": 0,
                "usage": 0,
            },
            "period": ["2022-10-07T11:12:48", "2022-11-07T11:12:48"],
        }
        assert self.organization.customer_id == "cus_123"

    @patch("ee.api.billing.requests.get")
    def test_organization_usage_count_with_demo_project(self, mock_request, *args):
        def mock_implementation(url: str, headers: Any = None, params: Any = None) -> MagicMock:
            mock = MagicMock()
            mock.status_code = 404

            if "api/billing/portal" in url:
                mock.status_code = 200
                mock.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}
            elif "api/billing" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_response(
                    # Set usage to none so it is calculated from scratch
                    customer=create_billing_customer(has_active_subscription=False, usage=None)
                )

            return mock

        mock_request.side_effect = mock_implementation

        self.organization.customer_id = None
        self.organization.usage = None
        self.organization.save()
        # Create a demo project
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        response = self.client.post("/api/projects/", {"name": "Test", "is_demo": True})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Team.objects.count(), 3)

        demo_team = Team.objects.filter(is_demo=True).first()

        # We create some events for the demo project
        with self.settings(USE_TZ=False):
            distinct_id = str(uuid4())
            for _ in range(0, 10):
                _create_event(
                    distinct_id=distinct_id,
                    event="$demo-event",
                    properties={"$lib": "$mobile"},
                    timestamp=now() - relativedelta(hours=12),
                    team=demo_team,
                )
            flush_persons_and_events()

        assert not self.organization.usage
        res = self.client.get("/api/billing-v2")
        assert res.status_code == 200
        self.organization.refresh_from_db()

        assert self.organization.usage == {
            "events": {"limit": None, "usage": 0, "todays_usage": 0},
            "recordings": {"limit": None, "usage": 0, "todays_usage": 0},
            "rows_synced": {"limit": None, "usage": 0, "todays_usage": 0},
            "period": ["2022-10-07T11:12:48", "2022-11-07T11:12:48"],
        }
