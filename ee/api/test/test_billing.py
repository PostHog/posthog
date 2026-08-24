import json
from datetime import datetime, timedelta
from typing import Any, cast, get_args
from uuid import uuid4
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, _create_event, flush_persons_and_events
from unittest import TestCase
from unittest.mock import MagicMock, PropertyMock, patch

from django.utils.timezone import now

import jwt
from dateutil.relativedelta import relativedelta
from parameterized import parameterized
from requests import Response, get
from rest_framework import status

from posthog.cloud_utils import TEST_clear_instance_license_cache, get_cached_instance_license
from posthog.constants import AvailableFeature
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal, hash_key_value

from ee.api.billing import (
    MEMBER_BILLING_USAGE_SPEND_READ_ACCESS_FLAG,
    OWNER_ONLY_BILLING_FLAG,
    BillingUsageRequestSerializer,
    BillingViewset,
    HasBillingUsageSpendReadAccess,
)
from ee.api.test.base import APILicensedTest
from ee.billing.billing_types import USAGE_TYPE_OPTIONS, BillingPeriod, CustomerInfo, CustomerProduct, UsageType
from ee.billing.quota_limiting import QuotaResource
from ee.billing.test.test_billing_manager import create_default_products_response
from ee.models.license import License
from ee.models.rbac.access_control import AccessControl


def create_usage_summary(**kwargs) -> dict[str, Any]:
    data: dict[str, Any] = {
        "period": ["2022-10-07T11:12:48", "2022-11-07T11:12:48"],
    }
    for resource in QuotaResource:
        data[resource.value] = {"limit": None, "usage": 0, "todays_usage": 0}

    data.update(kwargs)
    return data


def create_billing_response(**kwargs) -> dict[str, Any]:
    data: Any = {"license": {"type": "cloud"}}
    data.update(kwargs)
    return data


def create_missing_billing_customer(**kwargs) -> CustomerInfo:
    data: dict[str, Any] = {
        "customer_id": "cus_123",
        "deactivated": False,
        "custom_limits_usd": {},
        "has_active_subscription": False,
        "current_total_amount_usd": "0.00",
        "current_total_amount_usd_after_discount": "0.00",
        "discount_percent": None,
        "discount_amount_usd": None,
        "customer_trust_scores": {},
        "products": None,
        "billing_period": BillingPeriod(
            current_period_start="2022-10-07T11:12:48",
            current_period_end="2022-11-07T11:12:48",
            interval="month",
        ),
        "usage_summary": create_usage_summary(),
        "free_trial_until": None,
        "available_product_features": [],
    }
    data.update(kwargs)
    return cast(CustomerInfo, data)


def create_billing_customer(**kwargs) -> CustomerInfo:
    data: dict[str, Any] = {
        "customer_id": "cus_123",
        "custom_limits_usd": {},
        "has_active_subscription": True,
        "current_total_amount_usd": "100.00",
        "current_total_amount_usd_after_discount": "100.00",
        "discount_percent": None,
        "discount_amount_usd": None,
        "deactivated": False,
        "products": [
            {
                "name": "Product OS",
                "description": "Product Analytics, event pipelines, data warehousing",
                "price_description": None,
                "type": "product_analytics",
                "image_url": "https://posthog.com/static/images/product-os.png",
                "free_allocation": 10000,
                "tiers": [
                    {"unit_amount_usd": "0.00", "up_to": 1000000, "current_amount_usd": "0.00"},
                    {"unit_amount_usd": "0.00045", "up_to": 2000000, "current_amount_usd": "0.00"},
                ],
                "tiered": True,
                "unit_amount_usd": "0.00",
                "current_amount_usd": "0.00",
                "current_usage": 0,
                "usage_limit": None,
                "has_exceeded_limit": False,
                "percentage_usage": 0,
                "projected_usage": 0,
                "projected_amount_usd": "0.00",
                "projected_amount_usd_with_limit": "0.00",
                "usage_key": "events",
                "addons": [
                    {
                        "name": "Addon",
                        "description": "Test Addon",
                        "price_description": None,
                        "type": "addon",
                        "image_url": "https://posthog.com/static/images/product-os.png",
                        "free_allocation": 10000,
                        "tiers": [
                            {"unit_amount_usd": "0.00", "up_to": 1000000, "current_amount_usd": "0.00"},
                            {"unit_amount_usd": "0.0000135", "up_to": 2000000, "current_amount_usd": "0.00"},
                        ],
                        "tiered": True,
                        "unit_amount_usd": "0.00",
                        "current_amount_usd": "0.00",
                        "current_usage": 0,
                        "usage_limit": None,
                        "has_exceeded_limit": False,
                        "percentage_usage": 0,
                        "projected_usage": 0,
                        "projected_amount_usd": "0.00",
                        "usage_key": "events",
                        "subscribed": True,
                    }
                ],
            }
        ],
        "customer_trust_scores": {
            "surveys": 15,
            "feature_flags": 15,
            "data_warehouse": 15,
            "session_replay": 15,
            "product_analytics": 15,
        },
        "billing_period": BillingPeriod(
            current_period_start="2022-10-07T11:12:48",
            current_period_end="2022-11-07T11:12:48",
            interval="month",
        ),
        "usage_summary": create_usage_summary(),
        "free_trial_until": None,
        "available_product_features": [],
    }
    data.update(kwargs)
    return cast(CustomerInfo, data)


def create_billing_products_response(**kwargs) -> dict[str, list[CustomerProduct]]:
    data: Any = {
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
                        "current_usage": 0,
                        "flat_amount_usd": "0",
                        "projected_amount_usd": "None",
                        "projected_usage": None,
                    },
                    {
                        "unit_amount_usd": "0.00045",
                        "up_to": 2000000,
                        "current_amount_usd": "0.00",
                        "current_usage": 0,
                        "flat_amount_usd": "0",
                        "projected_amount_usd": "None",
                        "projected_usage": None,
                    },
                ],
                "addons": [
                    {
                        "current_amount_usd": 0.0,
                        "current_usage": 0,
                        "description": "Test Addon",
                        "free_allocation": 10000,
                        "has_exceeded_limit": False,
                        "image_url": "https://posthog.com/static/images/product-os.png",
                        "name": "Addon",
                        "percentage_usage": 0,
                        "price_description": None,
                        "projected_amount_usd": "0.00",
                        "projected_usage": 0,
                        "subscribed": True,
                        "tiered": True,
                        "tiers": [
                            {
                                "current_amount_usd": "0.00",
                                "current_usage": 0,
                                "flat_amount_usd": "0",
                                "projected_amount_usd": "None",
                                "projected_usage": None,
                                "unit_amount_usd": "0.00",
                                "up_to": 1000000,
                            },
                            {
                                "current_amount_usd": "0.00",
                                "current_usage": 0,
                                "flat_amount_usd": "0",
                                "projected_amount_usd": "None",
                                "projected_usage": None,
                                "unit_amount_usd": "0.0000135",
                                "up_to": 2000000,
                            },
                        ],
                        "type": "events",
                        "unit_amount_usd": "0.00",
                        "usage_key": "events",
                        "usage_limit": None,
                    },
                ],
                "tiered": True,
                "unit_amount_usd": "0.00",
                "current_amount_usd": 0.0,
                "current_usage": 0,
                "usage_limit": None,
                "has_exceeded_limit": False,
                "percentage_usage": 0,
                "projected_usage": 0,
                "projected_amount": 0,
                "projected_amount_usd": 0.00,
                "projected_amount_usd_with_limit": 0.00,
                "usage_key": "events",
            }
        ]
    }
    data.update(kwargs)
    return cast(dict[str, list[CustomerProduct]], data)


class TestUnlicensedBillingAPI(APIBaseTest):
    @patch("ee.api.billing.requests.get")
    @freeze_time("2022-01-01")
    def test_billing_calls_the_service_without_token(self, mock_request):
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
                mock.json.return_value = create_default_products_response()

            return mock

        mock_request.side_effect = mock_implementation

        TEST_clear_instance_license_cache()
        res = self.client.get("/api/billing")
        assert res.status_code == 200
        assert res.json() == {
            "available_product_features": [],
            "products": create_default_products_response()["products"],
        }

    def test_license_patch_denied_for_members(self):
        # Unlicensed instance, so the permission layer (not the "license already exists"
        # guard) decides the outcome. Setting the instance-wide license key is an
        # admin-only action.
        TEST_clear_instance_license_cache()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.patch("/api/billing/license", {}, content_type="application/json")
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestBillingAPI(APILicensedTest):
    def test_billing_fails_for_old_license_type(self):
        self.license.key = "test_key"
        self.license.save()
        TEST_clear_instance_license_cache()

        res = self.client.get("/api/billing")
        assert res.status_code == 404
        assert res.json()["detail"] == "Billing is not supported for this license type"

    @patch("ee.api.billing.requests.get")
    @freeze_time("2022-01-01")
    def test_billing_calls_the_service_with_appropriate_token(self, mock_request):
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

        self.client.get("/api/billing")
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
            "distinct_id": str(self.user.distinct_id),
            "exp": 1640996100,
            "id": self.license.key.split("::")[0],
            "organization_id": str(self.organization.id),
            "organization_name": "Test",
            "organization_role": "member",
        }

    @patch("ee.api.billing.requests.get")
    def test_billing_returns_if_billing_exists(self, mock_request):
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
        response = self.client.get("/api/billing")
        assert response.status_code == status.HTTP_200_OK

        assert response.json() == {
            "customer_id": "cus_123",
            "customer_trust_scores": {
                "data_warehouse": 15,
                "feature_flags": 15,
                "product_analytics": 15,
                "session_replay": 15,
                "surveys": 15,
            },
            "license": {"plan": "cloud"},
            "available_product_features": [],
            "custom_limits_usd": {},
            "has_active_subscription": True,
            "stripe_portal_url": "http://localhost:8010/api/billing/portal",
            "current_total_amount_usd": "100.00",
            "current_total_amount_usd_after_discount": "100.00",
            "discount_percent": None,
            "discount_amount_usd": None,
            "deactivated": False,
            "products": [
                {
                    "name": "Product OS",
                    "description": "Product Analytics, event pipelines, data warehousing",
                    "price_description": None,
                    "type": "product_analytics",
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
                            "current_amount_usd": "0.00",
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
                    "projected_amount_usd_with_limit": "0.00",
                    "projected_usage": 0,
                    "usage_key": "events",
                    "addons": [
                        {
                            "current_amount_usd": "0.00",
                            "current_usage": 0,
                            "description": "Test Addon",
                            "free_allocation": 10000,
                            "has_exceeded_limit": False,
                            "image_url": "https://posthog.com/static/images/product-os.png",
                            "name": "Addon",
                            "percentage_usage": 0,
                            "price_description": None,
                            "projected_amount_usd": "0.00",
                            "projected_usage": 0,
                            "subscribed": True,
                            "tiered": True,
                            "tiers": [
                                {
                                    "current_amount_usd": "0.00",
                                    "unit_amount_usd": "0.00",
                                    "up_to": 1000000,
                                },
                                {
                                    "current_amount_usd": "0.00",
                                    "unit_amount_usd": "0.0000135",
                                    "up_to": 2000000,
                                },
                            ],
                            "type": "addon",
                            "unit_amount_usd": "0.00",
                            "usage_key": "events",
                            "usage_limit": None,
                        },
                    ],
                },
            ],
            "billing_period": {
                "current_period_start": "2022-10-07T11:12:48",
                "current_period_end": "2022-11-07T11:12:48",
                "interval": "month",
            },
            "usage_summary": create_usage_summary(),
            "free_trial_until": None,
        }

    @patch("ee.api.billing.requests.get")
    def test_billing_returns_if_doesnt_exist(self, mock_request):
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

        response = self.client.get("/api/billing")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "customer_id": "cus_123",
            "customer_trust_scores": {},
            "license": {"plan": "cloud"},
            "custom_limits_usd": {},
            "has_active_subscription": False,
            "available_product_features": [],
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
                            "current_usage": 0,
                            "flat_amount_usd": "0",
                            "projected_amount_usd": "None",
                            "projected_usage": None,
                        },
                        {
                            "unit_amount_usd": "0.00045",
                            "up_to": 2000000,
                            "current_amount_usd": "0.00",
                            "current_usage": 0,
                            "flat_amount_usd": "0",
                            "projected_amount_usd": "None",
                            "projected_usage": None,
                        },
                    ],
                    "current_usage": 0,
                    "percentage_usage": 0,
                    "current_amount_usd": 0.0,
                    "has_exceeded_limit": False,
                    "projected_amount": 0,
                    "projected_amount_usd": 0.0,
                    "projected_amount_usd_with_limit": 0.0,
                    "projected_usage": 0,
                    "tiered": True,
                    "unit_amount_usd": "0.00",
                    "usage_limit": None,
                    "image_url": "https://posthog.com/static/images/product-os.png",
                    "usage_key": "events",
                    "addons": [
                        {
                            "current_amount_usd": 0.0,
                            "current_usage": 0,
                            "description": "Test Addon",
                            "free_allocation": 10000,
                            "has_exceeded_limit": False,
                            "image_url": "https://posthog.com/static/images/product-os.png",
                            "name": "Addon",
                            "percentage_usage": 0,
                            "price_description": None,
                            "projected_amount_usd": "0.00",
                            "projected_usage": 0,
                            "subscribed": True,
                            "tiered": True,
                            "tiers": [
                                {
                                    "current_amount_usd": "0.00",
                                    "current_usage": 0,
                                    "flat_amount_usd": "0",
                                    "projected_amount_usd": "None",
                                    "projected_usage": None,
                                    "unit_amount_usd": "0.00",
                                    "up_to": 1000000,
                                },
                                {
                                    "current_amount_usd": "0.00",
                                    "current_usage": 0,
                                    "flat_amount_usd": "0",
                                    "projected_amount_usd": "None",
                                    "projected_usage": None,
                                    "unit_amount_usd": "0.0000135",
                                    "up_to": 2000000,
                                },
                            ],
                            "type": "events",
                            "unit_amount_usd": "0.00",
                            "usage_key": "events",
                            "usage_limit": None,
                        },
                    ],
                }
            ],
            "billing_period": {
                "current_period_start": "2022-10-07T11:12:48",
                "current_period_end": "2022-11-07T11:12:48",
                "interval": "month",
            },
            "usage_summary": create_usage_summary(),
            "free_trial_until": None,
            "current_total_amount_usd": "0.00",
            "current_total_amount_usd_after_discount": "0.00",
            "discount_percent": None,
            "discount_amount_usd": None,
            "deactivated": False,
            "stripe_portal_url": "http://localhost:8010/api/billing/portal",
        }

    @patch("ee.api.billing.requests.get")
    def test_billing_stores_valid_license(self, mock_request):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.license.delete()

        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {
            "license": {
                "type": "scale",
            }
        }
        response = self.client.patch(
            "/api/billing/license",
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
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.license.delete()

        mock_request.return_value.status_code = 403
        mock_request.return_value.json.return_value = {}
        response = self.client.patch(
            "/api/billing/license",
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
        self.client.get("/api/billing")
        self.license.refresh_from_db()

        self.license.valid_until = datetime(2022, 1, 2, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
        self.license.save()
        assert self.license.plan == "scale"
        TEST_clear_instance_license_cache()
        license = get_cached_instance_license()
        assert license is not None
        assert license.plan == "scale"
        assert license.valid_until == datetime(2022, 1, 2, 0, 0, 0, tzinfo=ZoneInfo("UTC"))

        mock_request.return_value.json.return_value = {
            "license": {
                "type": "enterprise",
            },
            "customer": create_billing_customer(),
        }

        self.client.get("/api/billing")
        license = get_cached_instance_license()
        assert license is not None
        assert license.plan == "enterprise"
        # Should be extended by 30 days
        assert license.valid_until == datetime(2022, 1, 31, 12, 0, 0, tzinfo=ZoneInfo("UTC"))

    @patch("ee.api.billing.requests.get")
    def test_organization_available_product_features_updated_if_different(self, mock_request):
        def mock_implementation(url: str, headers: Any = None, params: Any = None) -> MagicMock:
            mock = MagicMock()
            mock.status_code = 404

            if "api/billing/portal" in url:
                mock.status_code = 200
                mock.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}
            elif "api/billing" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_response(
                    customer=create_billing_customer(
                        available_product_features=[
                            {"key": "feature1", "name": "feature1"},
                            {"key": "feature2", "name": "feature2"},
                        ]
                    )
                )

            return mock

        mock_request.side_effect = mock_implementation

        self.organization.available_product_features = []
        self.organization.save()

        assert self.organization.available_product_features == []
        self.client.get("/api/billing")
        self.organization.refresh_from_db()
        assert self.organization.available_product_features == [
            {
                "key": "feature1",
                "name": "feature1",
            },
            {"key": "feature2", "name": "feature2"},
        ]

    @patch("ee.api.billing.requests.get")
    def test_organization_update_usage(self, mock_request):
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
                    customer=create_billing_customer(has_active_subscription=True),
                )
                mock.json.return_value["customer"]["usage_summary"]["events"]["usage"] = 1000
            elif "api/products" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_products_response()

            return mock

        mock_request.side_effect = mock_implementation

        self.assertIsNone(self.organization.usage)
        res = self.client.get("/api/billing")
        assert res.status_code == 200
        organization = Team.objects.get(pk=self.team.pk).organization
        assert organization.usage is not None
        TestCase().assertDictEqual(
            organization.usage,
            create_usage_summary(events={"usage": 1000, "limit": None, "todays_usage": 0}),
        )

        self.organization.usage = {"events": {"limit": None, "usage": 1000, "todays_usage": 1100000}}
        self.organization.save()

        res = self.client.get("/api/billing")
        assert res.status_code == 200
        res_json = res.json()
        # Should update product usage to reflect today's usage
        assert res_json["products"][0]["current_usage"] == 1101000
        assert res_json["products"][0]["current_amount_usd"] == "0.00"
        assert res_json["products"][0]["tiers"][0]["current_amount_usd"] == "0.00"
        assert res_json["products"][0]["tiers"][1]["current_amount_usd"] == "0.00"

        assert res_json["products"][0]["addons"][0]["current_usage"] == 0
        assert res_json["products"][0]["addons"][0]["current_amount_usd"] == "0.00"
        assert res_json["products"][0]["addons"][0]["tiers"][0]["current_amount_usd"] == "0.00"
        assert res_json["products"][0]["addons"][0]["tiers"][1]["current_amount_usd"] == "0.00"

    @patch("ee.api.billing.requests.get")
    def test_organization_usage_count_with_demo_project(self, mock_request, *args):
        def mock_implementation(url: str, headers: Any = None, params: Any = None) -> MagicMock | Response:
            mock = MagicMock()
            if "api/billing/portal" in url:
                mock.status_code = 200
                mock.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}
                return mock
            elif "api/billing" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_response(
                    # Set usage to none so it is calculated from scratch
                    customer=create_billing_customer(has_active_subscription=False, usage=None)
                )
                return mock
            else:
                return get(url, headers=headers, params=params)

        mock_request.side_effect = mock_implementation

        self.organization.customer_id = None
        self.organization.usage = None
        self.organization.save()
        # Create a demo project
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.assertEqual(Team.objects.count(), 1)
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
        res = self.client.get("/api/billing")
        assert res.status_code == 200
        self.organization.refresh_from_db()
        assert self.organization.usage == create_usage_summary()

    @patch("ee.api.billing.requests.get")
    def test_org_trust_score_updated(self, mock_request):
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
        # For key values check: QuotaResource values
        self.organization.customer_trust_scores = {
            "events": 0,
            "exceptions": 0,
            "recordings": 0,
            "rows_synced": 0,
            "feature_flags": 0,
            "api_queries_read_bytes": 17,
            "surveys": 0,
        }
        self.organization.save()

        res = self.client.get("/api/billing")
        assert res.status_code == 200
        self.organization.refresh_from_db()

        assert self.organization.customer_trust_scores == {
            "events": 15,
            "exceptions": 0,
            "recordings": 0,
            "rows_synced": 0,
            "feature_flags": 0,
            "api_queries_read_bytes": 17,
            "surveys": 0,
        }

    @patch("ee.api.billing.requests.get")
    def test_billing_with_supported_params(self, mock_get):
        """Test that the include_forecasting param is passed through to the billing service."""

        def mock_implementation(url: str, headers: Any = None, params: Any = None) -> MagicMock:
            mock = MagicMock()
            mock.status_code = 200

            if "api/billing/portal" in url:
                mock.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}
            elif "api/billing" in url:
                mock.json.return_value = create_billing_response(
                    customer=create_billing_customer(has_active_subscription=True)
                )

            return mock

        mock_get.side_effect = mock_implementation

        response = self.client.get("/api/billing/?include_forecasting=true")
        assert response.status_code == 200

        # Verify the billing service was called with the correct query param
        billing_calls = [
            call
            for call in mock_get.call_args_list
            if "api/billing" in call[0][0] and "api/billing/portal" not in call[0][0]
        ]
        assert len(billing_calls) == 1
        assert billing_calls[0].kwargs["params"] == {"include_forecasting": "true"}


class TestPortalBillingAPI(APILicensedTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    @patch("ee.api.billing.requests.get")
    def test_portal_success(self, mock_request):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {"url": "https://billing.stripe.com/p/session/test_1234"}

        response = self.client.get("/api/billing/portal")

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn("https://billing.stripe.com/p/session/test_1234", cast(Any, response).url)


class TestActivateBillingAPI(APILicensedTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    @patch("ee.billing.billing_manager.BillingManager.activate_subscription")
    def test_activate_post_success(self, mock_activate_subscription):
        mock_activate_subscription.return_value = {"success": True, "products": ["product_analytics"]}

        url = "/api/billing/activate"
        data = {"products": "all_products:"}

        response = self.client.post(url, data, content_type="application/json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True, "products": ["product_analytics"]})
        mock_activate_subscription.assert_called_once_with(self.organization, {"products": "all_products:"})

    def test_activate_get_returns_405(self):
        url = "/api/billing/activate"
        response = self.client.get(url, {"products": "product_1:plan_1"})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    @patch("ee.billing.billing_manager.BillingManager.deactivate_products")
    @patch("ee.billing.billing_manager.BillingManager.get_billing")
    def test_deactivate_success(self, mock_get_billing, mock_deactivate_products):
        mock_deactivate_products.return_value = MagicMock()
        mock_get_billing.return_value = {
            "available_features": [],
            "products": [],
        }

        url = "/api/billing/deactivate"
        data = {"products": "product_1"}

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_deactivate_products.assert_called_once_with(self.organization, "product_1")
        mock_get_billing.assert_called_once_with(self.organization, {})

    def test_deactivate_failure(self):
        url = "/api/billing/deactivate"
        data = {"none": "nothing"}

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestStartupApplicationBillingAPI(APILicensedTest):
    def setUp(self):
        super().setUp()
        # Set user as admin/owner by default
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        self.url = "/api/billing/startups/apply"
        self.data = {"organization_id": str(self.organization.id)}

    @patch("ee.billing.billing_manager.BillingManager.apply_startup_program")
    def test_startup_apply_owner_success(self, mock_apply_startup_program):
        mock_apply_startup_program.return_value = {"success": True}

        response = self.client.post(self.url, self.data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"success": True})
        mock_apply_startup_program.assert_called_once()

    def test_startup_apply_non_admin_failure(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(self.url, self.data)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_startup_apply_missing_org_id(self):
        empty_data: dict[str, Any] = {}

        response = self.client.post(self.url, empty_data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "This field is required.",
                "attr": "organization_id",
            },
        )

    @patch("ee.billing.billing_manager.BillingManager.apply_startup_program")
    def test_startup_apply_passes_user_info(self, mock_apply_startup_program):
        mock_apply_startup_program.return_value = {"success": True}

        # Set user properties
        self.user.email = "test@example.com"
        self.user.first_name = "Test"
        self.user.last_name = "User"
        self.user.save()

        # Add additional data fields
        data = {
            **self.data,
            "raised": "1000000",
            "incorporation_date": "2023-01-01",
        }

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        expected_data = {
            "organization_id": str(self.organization.id),
            "raised": "1000000",
            "incorporation_date": "2023-01-01",
            "email": "test@example.com",
            "first_name": "Test",
            "last_name": "User",
        }

        # Check that apply_startup_program was called with the organization and the expected data
        mock_apply_startup_program.assert_called_once()
        _, call_args, _ = mock_apply_startup_program.mock_calls[0]
        self.assertEqual(call_args[0], self.organization)
        self.assertEqual(call_args[1], expected_data)


class TestCouponClaimBillingAPI(APILicensedTest):
    def setUp(self):
        super().setUp()
        # Set user as admin by default
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        self.url = "/api/billing/coupons/claim"
        self.data = {"code": "TEST-CODE-123"}

    @patch("ee.billing.billing_manager.BillingManager.claim_coupon")
    def test_claim_coupon_success(self, mock_claim_coupon):
        mock_claim_coupon.return_value = {
            "success": True,
            "code": "TEST-CODE-123",
            "expires_at": "2026-01-01T00:00:00Z",
        }

        response = self.client.post(self.url, self.data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["success"], True)
        self.assertEqual(response.json()["code"], "TEST-CODE-123")
        mock_claim_coupon.assert_called_once_with(self.organization, {"code": "TEST-CODE-123"})

    def test_claim_coupon_non_admin_failure(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(self.url, self.data)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_claim_coupon_missing_code(self):
        empty_data: dict[str, Any] = {}

        response = self.client.post(self.url, empty_data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "This field is required.",
                "attr": "code",
            },
        )

    @patch("ee.billing.billing_manager.BillingManager.claim_coupon")
    def test_claim_coupon_billing_error_with_detail(self, mock_claim_coupon):
        # DRF validation error
        mock_claim_coupon.side_effect = Exception(
            "Billing service returned bad status code: 400",
            "body:",
            {"detail": "Customer has already claimed a coupon from this campaign."},
        )

        response = self.client.post(self.url, self.data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_json = response.json()
        self.assertEqual(response_json["detail"], "Customer has already claimed a coupon from this campaign.")


class TestBillingUsageRequestSerializer(TestCase):
    def test_valid_dates(self):
        serializer = BillingUsageRequestSerializer(data={"start_date": "2025-01-01", "end_date": "2025-01-31"})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["start_date"], "2025-01-01")
        self.assertEqual(serializer.validated_data["end_date"], "2025-01-31")

    @freeze_time("2025-02-15")
    def test_relative_dates(self):
        serializer = BillingUsageRequestSerializer(data={"start_date": "-7d", "end_date": "-1d"})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["start_date"], "2025-02-08")
        self.assertEqual(serializer.validated_data["end_date"], "2025-02-14")

    @freeze_time("2025-02-15")
    def test_start_date_all_defaults_end_date_to_today(self):
        serializer = BillingUsageRequestSerializer(data={"start_date": "all"})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["start_date"], "2020-01-01")
        self.assertEqual(serializer.validated_data["end_date"], "2025-02-15")

    @freeze_time("2025-02-15")
    def test_start_date_without_end_date_defaults_end_date_to_today(self):
        serializer = BillingUsageRequestSerializer(data={"start_date": "2025-01-01"})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["start_date"], "2025-01-01")
        self.assertEqual(serializer.validated_data["end_date"], "2025-02-15")

    def test_passthrough_fields(self):
        data = {
            "usage_types": '["event_count_in_period","recording_count_in_period"]',
            "team_ids": "[1,2,3]",
            "breakdowns": '["type","team"]',
            "interval": "week",
        }
        serializer = BillingUsageRequestSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        for key, value in data.items():
            self.assertEqual(serializer.validated_data[key], value)

    def test_usage_type_options_match_usage_type_literal(self):
        self.assertEqual(
            {option["value"] for option in USAGE_TYPE_OPTIONS},
            set(get_args(UsageType)),
        )

    @parameterized.expand(
        [
            ("usage_types_comma_separated", "usage_types", "event_count_in_period, recording_count_in_period"),
            ("usage_types_json_non_array", "usage_types", '"event_count_in_period"'),
            ("team_ids_comma_separated", "team_ids", "1,2,3"),
            ("team_ids_json_string_values", "team_ids", '["1","2"]'),
            ("breakdowns_comma_separated", "breakdowns", "type,team"),
            ("breakdowns_unknown_values", "breakdowns", '["type","project"]'),
        ]
    )
    def test_rejects_invalid_json_array_fields(self, _case_name: str, field_name: str, value: str):
        serializer = BillingUsageRequestSerializer(data={field_name: value})
        self.assertFalse(serializer.is_valid())
        self.assertIn(field_name, serializer.errors)

    def test_empty_and_null_dates_are_valid(self):
        serializer = BillingUsageRequestSerializer(data={"start_date": "", "end_date": None})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertIsNone(serializer.validated_data.get("start_date"))
        self.assertIsNone(serializer.validated_data.get("end_date"))


class TestBillingUsageAndSpendAPI(APILicensedTest):
    MOCK_USAGE_DATA = {"results": [{"data": [1, 2], "count": 2}]}
    MOCK_SPEND_DATA = {"results": [{"spend": 100.0, "usage": 10000}]}

    def setUp(self):
        super().setUp()
        # Ensure the user is an admin for these tests by default
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _personal_api_key_headers(self, scopes: list[str], scoped_teams: list[int] | None = None) -> dict[str, str]:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Test Key",
            user=self.user,
            secure_value=hash_key_value(token),
            scopes=scopes,
            scoped_teams=scoped_teams,
        )
        self.client.logout()
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def _oauth_token_headers(self, scopes: list[str], scoped_teams: list[int] | None = None) -> dict[str, str]:
        oauth_application = OAuthApplication.objects.create(
            name="Billing MCP Test OAuth App",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
        )
        token = f"pha_billing_mcp_test_{uuid4().hex}"
        OAuthAccessToken.objects.create(
            user=self.user,
            application=oauth_application,
            token=token,
            expires=now() + timedelta(hours=1),
            scope=" ".join(scopes),
            scoped_teams=scoped_teams,
        )
        self.client.logout()
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def _token_headers(
        self, token_type: str, scopes: list[str], scoped_teams: list[int] | None = None
    ) -> dict[str, str]:
        if token_type == "personal":
            return self._personal_api_key_headers(scopes, scoped_teams=scoped_teams)
        if token_type == "oauth":
            return self._oauth_token_headers(scopes, scoped_teams=scoped_teams)
        raise AssertionError(f"Unknown token type: {token_type}")

    def test_scope_actions_are_read_only(self):
        self.assertEqual(BillingViewset.scope_object, "billing")
        self.assertEqual(BillingViewset.scope_object_read_actions, ["list", "usage", "spend"])
        self.assertEqual(BillingViewset.scope_object_write_actions, [])

    @patch("ee.billing.billing_manager.BillingManager.update_billing")
    def test_billing_write_scope_does_not_allow_patch_personal_api_key(self, mock_update_billing):
        headers = self._personal_api_key_headers(["billing:write"], scoped_teams=[self.team.pk])

        response = self.client.patch(
            "/api/billing//",
            data={"custom_limits_usd": {"events": 10}},
            content_type="application/json",
            HTTP_AUTHORIZATION=headers["HTTP_AUTHORIZATION"],
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_update_billing.assert_not_called()

    @parameterized.expand(
        [
            ("list", "get", "/api/billing/", None, "ee.billing.billing_manager.BillingManager.get_billing"),
            (
                "usage",
                "get",
                "/api/billing/usage/",
                {"start_date": "2025-01-01"},
                "ee.billing.billing_manager.BillingManager.get_usage_data",
            ),
            (
                "spend",
                "get",
                "/api/billing/spend/",
                {"start_date": "2025-01-01"},
                "ee.billing.billing_manager.BillingManager.get_spend_data",
            ),
        ]
    )
    @patch("ee.api.billing.posthog_feature_flag_enabled", return_value=False)
    def test_billing_read_scope_actions_still_require_billing_access(
        self, action_name, method_name, url, data, manager_method_path, _mock_feature_enabled
    ):
        self.assertIn(action_name, BillingViewset.scope_object_read_actions)
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        headers = self._personal_api_key_headers(["billing:read"], scoped_teams=[self.team.pk])

        with patch(manager_method_path) as mock_manager_method:
            response = getattr(self.client, method_name)(
                url,
                data=data,
                HTTP_AUTHORIZATION=headers["HTTP_AUTHORIZATION"],
            )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_manager_method.assert_not_called()

    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    def test_get_usage_success(self, mock_get_usage_data):
        mock_get_usage_data.return_value = self.MOCK_USAGE_DATA

        response = self.client.get(f"/api/billing/usage/?start_date=2025-01-01&team_ids=[{self.team.pk}]")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), self.MOCK_USAGE_DATA)
        mock_get_usage_data.assert_called_once()
        call_args = mock_get_usage_data.call_args[0]
        self.assertEqual(call_args[0], self.organization)  # First arg is organization
        passed_params = call_args[1]  # Second arg is params dict
        self.assertEqual(passed_params["start_date"], "2025-01-01")
        self.assertEqual(passed_params["team_ids"], f"[{str(self.team.pk)}]")
        self.assertEqual(passed_params["teams_map"], {self.team.pk: self.team.name})

    @patch("ee.billing.billing_manager.BillingManager.get_spend_data")
    def test_get_spend_success(self, mock_get_spend_data):
        mock_get_spend_data.return_value = self.MOCK_SPEND_DATA

        response = self.client.get(
            "/api/billing/spend/",
            {
                "start_date": "2025-01-01",
                "usage_types": '["event_count_in_period"]',
                "team_ids": f"[{self.team.pk}]",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), self.MOCK_SPEND_DATA)
        mock_get_spend_data.assert_called_once()
        call_args = mock_get_spend_data.call_args[0]
        self.assertEqual(call_args[0], self.organization)
        passed_params = call_args[1]
        self.assertEqual(passed_params["start_date"], "2025-01-01")
        self.assertEqual(json.loads(passed_params["usage_types"]), ["event_count_in_period"])
        self.assertEqual(passed_params["team_ids"], f"[{str(self.team.pk)}]")
        self.assertEqual(passed_params["teams_map"], {self.team.pk: self.team.name})

    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    def test_get_usage_allows_wildcard_personal_api_key_for_admin(self, mock_get_usage_data):
        mock_get_usage_data.return_value = self.MOCK_USAGE_DATA
        headers = self._personal_api_key_headers(["*"])

        response = self.client.get(
            "/api/billing/usage/",
            {"start_date": "2025-01-01", "team_ids": f"[{self.team.pk}]"},
            HTTP_AUTHORIZATION=headers["HTTP_AUTHORIZATION"],
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), self.MOCK_USAGE_DATA)
        mock_get_usage_data.assert_called_once()

    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    def test_get_usage_allows_project_scoped_billing_read_personal_api_key_for_org_billing(self, mock_get_usage_data):
        mock_get_usage_data.return_value = self.MOCK_USAGE_DATA
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        headers = self._personal_api_key_headers(["billing:read"], scoped_teams=[self.team.pk])

        response = self.client.get(
            "/api/billing/usage/",
            {"start_date": "2025-01-01", "team_ids": f"[{other_team.pk}]"},
            HTTP_AUTHORIZATION=headers["HTTP_AUTHORIZATION"],
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        passed_params = mock_get_usage_data.call_args[0][1]
        self.assertEqual(passed_params["team_ids"], f"[{other_team.pk}]")
        self.assertEqual(
            passed_params["teams_map"],
            {
                self.team.pk: self.team.name,
                other_team.pk: other_team.name,
            },
        )

    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    def test_get_usage_allows_project_scoped_billing_read_oauth_token_for_org_billing(self, mock_get_usage_data):
        mock_get_usage_data.return_value = self.MOCK_USAGE_DATA
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        headers = self._oauth_token_headers(["billing:read"], scoped_teams=[self.team.pk])

        response = self.client.get(
            "/api/billing/usage/",
            {"start_date": "2025-01-01", "team_ids": f"[{other_team.pk}]"},
            HTTP_AUTHORIZATION=headers["HTTP_AUTHORIZATION"],
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(mock_get_usage_data.call_args[0][1]["team_ids"], f"[{other_team.pk}]")

    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    def test_get_usage_rejects_other_org_team_ids_for_project_scoped_billing_read(self, mock_get_usage_data):
        other_org = self.create_organization_with_features([])
        other_team = self.create_team_with_organization(other_org)
        headers = self._personal_api_key_headers(["billing:read"], scoped_teams=[self.team.pk])

        response = self.client.get(
            "/api/billing/usage/",
            {"start_date": "2025-01-01", "team_ids": f"[{other_team.pk}]"},
            HTTP_AUTHORIZATION=headers["HTTP_AUTHORIZATION"],
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_get_usage_data.assert_not_called()

    @patch("ee.billing.billing_manager.BillingManager.get_spend_data")
    def test_get_spend_rejects_other_org_team_ids_for_project_scoped_billing_read(self, mock_get_spend_data):
        other_org = self.create_organization_with_features([])
        other_team = self.create_team_with_organization(other_org)
        headers = self._personal_api_key_headers(["billing:read"], scoped_teams=[self.team.pk])

        response = self.client.get(
            "/api/billing/spend/",
            {"start_date": "2025-01-01", "team_ids": f"[{other_team.pk}]"},
            HTTP_AUTHORIZATION=headers["HTTP_AUTHORIZATION"],
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_get_spend_data.assert_not_called()

    def test_get_usage_rejects_personal_api_key_without_billing_read_scope(self):
        headers = self._personal_api_key_headers(["project:read"])
        response = self.client.get(
            "/api/billing/usage/",
            {"start_date": "2025-01-01"},
            HTTP_AUTHORIZATION=headers["HTTP_AUTHORIZATION"],
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_usage_rejects_billing_read_personal_api_key_for_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        headers = self._personal_api_key_headers(["billing:read"], scoped_teams=[self.team.pk])

        response = self.client.get(
            "/api/billing/usage/",
            {"start_date": "2025-01-01"},
            HTTP_AUTHORIZATION=headers["HTTP_AUTHORIZATION"],
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @parameterized.expand([("usage", "get_usage_data"), ("spend", "get_spend_data")])
    @patch("ee.api.billing.posthog_feature_flag_enabled")
    def test_member_billing_read_personal_api_key_can_read_usage_and_spend_when_flag_allows(
        self, endpoint: str, manager_method: str, mock_feature_enabled: MagicMock
    ):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        mock_feature_enabled.side_effect = self._member_access_flags
        headers = self._personal_api_key_headers(["billing:read"], scoped_teams=[self.team.pk])

        with patch(f"ee.billing.billing_manager.BillingManager.{manager_method}") as mock_fetch:
            mock_fetch.return_value = self.MOCK_USAGE_DATA if endpoint == "usage" else self.MOCK_SPEND_DATA
            response = self.client.get(
                f"/api/billing/{endpoint}/",
                {"start_date": "2025-01-01"},
                HTTP_AUTHORIZATION=headers["HTTP_AUTHORIZATION"],
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_fetch.assert_called_once()
        passed_params = mock_fetch.call_args[0][1]
        self.assertEqual(json.loads(passed_params["team_ids"]), [self.team.pk])
        self.assertEqual(passed_params["teams_map"], {self.team.pk: self.team.name})

    @parameterized.expand([("personal",), ("oauth",)])
    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    @patch("ee.api.billing.posthog_feature_flag_enabled")
    def test_member_token_scope_limits_injected_team_ids(
        self, token_type: str, mock_feature_enabled: MagicMock, mock_get_usage_data: MagicMock
    ):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        other_team = Team.objects.create(organization=self.organization, name="Other visible project")
        mock_feature_enabled.side_effect = self._member_access_flags
        mock_get_usage_data.return_value = self.MOCK_USAGE_DATA
        headers = self._token_headers(token_type, ["billing:read"], scoped_teams=[self.team.pk])

        response = self.client.get(
            "/api/billing/usage/",
            HTTP_AUTHORIZATION=headers["HTTP_AUTHORIZATION"],
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_get_usage_data.assert_called_once()
        passed_params = mock_get_usage_data.call_args[0][1]
        self.assertEqual(json.loads(passed_params["team_ids"]), [self.team.pk])
        self.assertEqual(passed_params["teams_map"], {self.team.pk: self.team.name})
        self.assertNotIn(other_team.pk, passed_params["teams_map"])

    @parameterized.expand([("personal",), ("oauth",)])
    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    @patch("ee.api.billing.posthog_feature_flag_enabled")
    def test_member_token_scope_rejects_requested_team_outside_token_scope(
        self, token_type: str, mock_feature_enabled: MagicMock, mock_get_usage_data: MagicMock
    ):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        other_team = Team.objects.create(organization=self.organization, name="Other visible project")
        mock_feature_enabled.side_effect = self._member_access_flags
        headers = self._token_headers(token_type, ["billing:read"], scoped_teams=[self.team.pk])

        response = self.client.get(
            "/api/billing/usage/",
            {"team_ids": f"[{other_team.pk}]"},
            HTTP_AUTHORIZATION=headers["HTTP_AUTHORIZATION"],
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_get_usage_data.assert_not_called()

    @patch("ee.billing.billing_manager.BillingManager.get_billing")
    def test_list_personal_api_key_uses_resolved_team_org_when_current_org_is_stale(self, mock_get_billing):
        other_org = self.create_organization_with_features([])
        self.create_team_with_organization(other_org)
        OrganizationMembership.objects.create(
            user=self.user,
            organization=other_org,
            level=OrganizationMembership.Level.ADMIN,
        )
        self.user.current_organization = other_org
        self.user.current_team = self.team
        self.user.save(update_fields=["current_organization", "current_team"])
        headers = self._personal_api_key_headers(["billing:read"], scoped_teams=[self.team.pk])
        mock_get_billing.return_value = create_billing_response(customer=create_billing_customer())

        response = self.client.get(
            "/api/billing/",
            HTTP_AUTHORIZATION=headers["HTTP_AUTHORIZATION"],
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_get_billing.assert_called_once()
        self.assertEqual(mock_get_billing.call_args.args[0], self.organization)

    @patch("ee.billing.billing_manager.BillingManager.get_billing")
    @patch("ee.api.billing.posthog_feature_flag_enabled")
    def test_list_rejects_billing_read_personal_api_key_for_member(self, mock_feature_enabled, mock_get_billing):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        mock_feature_enabled.side_effect = self._member_access_flags
        headers = self._personal_api_key_headers(["billing:read"], scoped_teams=[self.team.pk])

        response = self.client.get(
            "/api/billing/",
            HTTP_AUTHORIZATION=headers["HTTP_AUTHORIZATION"],
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_get_billing.assert_not_called()

    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    @patch("ee.api.billing.posthog_feature_flag_enabled", return_value=True)
    def test_owner_only_billing_rejects_admin_personal_api_key_usage_access(
        self, _mock_feature_enabled, mock_get_usage_data
    ):
        mock_get_usage_data.return_value = self.MOCK_USAGE_DATA
        headers = self._personal_api_key_headers(["billing:read"], scoped_teams=[self.team.pk])

        response = self.client.get(
            "/api/billing/usage/",
            {"start_date": "2025-01-01"},
            HTTP_AUTHORIZATION=headers["HTTP_AUTHORIZATION"],
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_get_usage_data.assert_not_called()

    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    @patch("ee.api.billing.posthog_feature_flag_enabled", return_value=True)
    def test_owner_only_billing_rejects_admin_usage_access(self, _mock_feature_enabled, mock_get_usage_data):
        mock_get_usage_data.return_value = self.MOCK_USAGE_DATA

        response = self.client.get("/api/billing/usage/", {"start_date": "2025-01-01"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_get_usage_data.assert_not_called()

    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    @patch("ee.api.billing.posthog_feature_flag_enabled", return_value=False)
    def test_admin_usage_access_allowed_when_owner_only_billing_is_off(self, mock_feature_enabled, mock_get_usage_data):
        mock_get_usage_data.return_value = self.MOCK_USAGE_DATA

        response = self.client.get("/api/billing/usage/", {"start_date": "2025-01-01"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_get_usage_data.assert_called_once()
        mock_feature_enabled.assert_any_call(
            OWNER_ONLY_BILLING_FLAG,
            str(self.user.distinct_id),
            organization_id=self.organization.id,
        )

    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    @patch("ee.api.billing.posthog_feature_flag_enabled", return_value=None)
    def test_owner_only_billing_rejects_admin_usage_access_when_flag_is_unknown(
        self, _mock_feature_enabled, mock_get_usage_data
    ):
        response = self.client.get("/api/billing/usage/", {"start_date": "2025-01-01"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_get_usage_data.assert_not_called()

    @patch("ee.api.billing.capture_exception")
    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    @patch("ee.api.billing.posthog_feature_flag_enabled", side_effect=Exception("flag lookup failed"))
    def test_owner_only_billing_rejects_admin_usage_access_when_flag_check_raises(
        self, _mock_feature_enabled, mock_get_usage_data, mock_capture_exception
    ):
        response = self.client.get("/api/billing/usage/", {"start_date": "2025-01-01"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_get_usage_data.assert_not_called()
        mock_capture_exception.assert_called_once()

    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    @patch("ee.api.billing.posthog_feature_flag_enabled")
    def test_owner_only_billing_rejects_admin_usage_access_without_distinct_id(
        self, mock_feature_enabled, mock_get_usage_data
    ):
        self.user.distinct_id = ""
        self.user.save()

        response = self.client.get("/api/billing/usage/", {"start_date": "2025-01-01"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_get_usage_data.assert_not_called()
        mock_feature_enabled.assert_not_called()

    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    @patch("ee.api.billing.posthog_feature_flag_enabled", return_value=True)
    def test_owner_only_billing_allows_owner_usage_access(self, _mock_feature_enabled, mock_get_usage_data):
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()
        mock_get_usage_data.return_value = self.MOCK_USAGE_DATA

        response = self.client.get("/api/billing/usage/", {"start_date": "2025-01-01"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_get_usage_data.assert_called_once()

    @patch("ee.billing.billing_manager.BillingManager.update_billing")
    @patch("ee.api.billing.posthog_feature_flag_enabled", return_value=True)
    def test_owner_only_billing_rejects_admin_limit_update(self, _mock_feature_enabled, mock_update_billing):
        response = self.client.patch(
            "/api/billing//",
            data={"custom_limits_usd": {"events": 10}},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_update_billing.assert_not_called()

    def test_mutating_action_rejects_wildcard_personal_api_key(self):
        headers = self._personal_api_key_headers(["*"])
        response = self.client.patch(
            "/api/billing//",
            data={"custom_limits_usd": {"events": 10}},
            content_type="application/json",
            HTTP_AUTHORIZATION=headers["HTTP_AUTHORIZATION"],
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("personal API key", response.json()["detail"])

    def test_get_usage_permission_denied_for_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.get("/api/billing/usage/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_spend_permission_denied_for_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response = self.client.get("/api/billing/spend/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @parameterized.expand(
        [
            ("usage", True, False, status.HTTP_200_OK),
            ("spend", True, False, status.HTTP_200_OK),
            ("usage", True, True, status.HTTP_403_FORBIDDEN),
            ("spend", True, True, status.HTTP_403_FORBIDDEN),
            ("usage", False, False, status.HTTP_403_FORBIDDEN),
            ("spend", False, False, status.HTTP_403_FORBIDDEN),
        ]
    )
    @patch("ee.billing.billing_manager.BillingManager.get_spend_data")
    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    @patch("ee.api.billing.posthog_feature_flag_enabled")
    def test_member_access_gated_by_flags(
        self,
        endpoint: str,
        member_access_flag: bool,
        owner_only_flag: bool,
        expected_status: int,
        mock_flag_eval: MagicMock,
        mock_get_usage_data: MagicMock,
        mock_get_spend_data: MagicMock,
    ):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        mock_flag_eval.side_effect = lambda key, *args, **kwargs: {
            MEMBER_BILLING_USAGE_SPEND_READ_ACCESS_FLAG: member_access_flag,
            OWNER_ONLY_BILLING_FLAG: owner_only_flag,
        }[key]
        mock_get_usage_data.return_value = self.MOCK_USAGE_DATA
        mock_get_spend_data.return_value = self.MOCK_SPEND_DATA

        response = self.client.get(f"/api/billing/{endpoint}/")

        self.assertEqual(response.status_code, expected_status)
        if expected_status == status.HTTP_403_FORBIDDEN:
            mock_get_usage_data.assert_not_called()
            mock_get_spend_data.assert_not_called()
        else:
            expected_data = self.MOCK_USAGE_DATA if endpoint == "usage" else self.MOCK_SPEND_DATA
            self.assertEqual(response.json(), expected_data)

    @patch("ee.api.billing.capture_exception")
    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    @patch("ee.api.billing.posthog_feature_flag_enabled")
    def test_member_access_denies_when_member_flag_check_raises(
        self,
        mock_feature_enabled: MagicMock,
        mock_get_usage_data: MagicMock,
        mock_capture_exception: MagicMock,
    ):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        def flag_response(key: str, *args: Any, **kwargs: Any) -> bool:
            if key == OWNER_ONLY_BILLING_FLAG:
                return False
            if key == MEMBER_BILLING_USAGE_SPEND_READ_ACCESS_FLAG:
                raise Exception("flag lookup failed")
            raise AssertionError(f"Unexpected flag: {key}")

        mock_feature_enabled.side_effect = flag_response

        response = self.client.get("/api/billing/usage/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_get_usage_data.assert_not_called()
        mock_capture_exception.assert_called_once()

    @parameterized.expand(
        [
            ("usage", OrganizationMembership.Level.ADMIN, False, status.HTTP_200_OK),
            ("spend", OrganizationMembership.Level.ADMIN, False, status.HTTP_200_OK),
            ("usage", OrganizationMembership.Level.ADMIN, True, status.HTTP_403_FORBIDDEN),
            ("spend", OrganizationMembership.Level.ADMIN, True, status.HTTP_403_FORBIDDEN),
            ("usage", OrganizationMembership.Level.OWNER, True, status.HTTP_200_OK),
            ("spend", OrganizationMembership.Level.OWNER, True, status.HTTP_200_OK),
        ]
    )
    @patch("ee.billing.billing_manager.BillingManager.get_spend_data")
    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    @patch("ee.api.billing.posthog_feature_flag_enabled")
    def test_admin_and_owner_access_gated_only_by_owner_only_billing(
        self,
        endpoint: str,
        level: OrganizationMembership.Level,
        owner_only_flag: bool,
        expected_status: int,
        mock_flag_eval: MagicMock,
        mock_get_usage_data: MagicMock,
        mock_get_spend_data: MagicMock,
    ):
        self.organization_membership.level = level
        self.organization_membership.save()
        mock_flag_eval.side_effect = lambda key, *args, **kwargs: {
            MEMBER_BILLING_USAGE_SPEND_READ_ACCESS_FLAG: False,
            OWNER_ONLY_BILLING_FLAG: owner_only_flag,
        }[key]
        mock_get_usage_data.return_value = self.MOCK_USAGE_DATA
        mock_get_spend_data.return_value = self.MOCK_SPEND_DATA

        response = self.client.get(f"/api/billing/{endpoint}/")

        self.assertEqual(response.status_code, expected_status)
        if expected_status == status.HTTP_403_FORBIDDEN:
            mock_get_usage_data.assert_not_called()
            mock_get_spend_data.assert_not_called()
        # The member read-access flag must never be consulted for admins and owners
        self.assertNotIn(
            MEMBER_BILLING_USAGE_SPEND_READ_ACCESS_FLAG,
            [call.args[0] for call in mock_flag_eval.call_args_list],
        )

    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    @patch("ee.api.billing.BillingViewset._get_teams_map")
    def test_get_usage_empty_teams_map_graceful_handling(self, mock_get_teams_map, mock_get_usage_data):
        mock_get_teams_map.return_value = {}
        mock_get_usage_data.return_value = self.MOCK_USAGE_DATA

        response = self.client.get(f"/api/billing/usage/?start_date=2025-01-01")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), self.MOCK_USAGE_DATA)
        mock_get_usage_data.assert_called_once()
        call_args = mock_get_usage_data.call_args[0]
        passed_params = call_args[1]
        self.assertEqual(passed_params["teams_map"], {})
        mock_get_teams_map.assert_called_once()

    @patch("ee.billing.billing_manager.BillingManager.get_spend_data")
    @patch("ee.api.billing.BillingViewset._get_teams_map")
    def test_get_spend_empty_teams_map_graceful_handling(self, mock_get_teams_map, mock_get_spend_data):
        mock_get_teams_map.return_value = {}
        mock_get_spend_data.return_value = self.MOCK_SPEND_DATA

        response = self.client.get(f"/api/billing/spend/?start_date=2025-01-01")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), self.MOCK_SPEND_DATA)
        mock_get_spend_data.assert_called_once()
        call_args = mock_get_spend_data.call_args[0]
        passed_params = call_args[1]
        self.assertEqual(passed_params["teams_map"], {})
        mock_get_teams_map.assert_called_once()

    @staticmethod
    def _member_access_flags(key: str, *args: Any, **kwargs: Any) -> bool:
        return key == MEMBER_BILLING_USAGE_SPEND_READ_ACCESS_FLAG

    def _make_team_private(self, team: Team) -> None:
        AccessControl.objects.create(
            team=team,
            resource="project",
            resource_id=str(team.id),
            access_level="none",
            organization_member=None,
            role=None,
        )

    def _setup_member_with_private_team(self) -> Team:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        private_team = Team.objects.create(organization=self.organization, name="Private Team")
        self._make_team_private(private_team)
        return private_team

    @parameterized.expand([("usage",), ("spend",)])
    @patch("ee.billing.billing_manager.BillingManager.get_spend_data")
    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    @patch("ee.api.billing.posthog_feature_flag_enabled")
    def test_member_team_ids_intersected_with_accessible_teams(
        self,
        endpoint: str,
        mock_flag_eval: MagicMock,
        mock_get_usage_data: MagicMock,
        mock_get_spend_data: MagicMock,
    ):
        private_team = self._setup_member_with_private_team()
        mock_flag_eval.side_effect = self._member_access_flags
        mock_get_usage_data.return_value = self.MOCK_USAGE_DATA
        mock_get_spend_data.return_value = self.MOCK_SPEND_DATA

        response = self.client.get(f"/api/billing/{endpoint}/?team_ids=[{self.team.pk},{private_team.pk}]")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_fetch = mock_get_usage_data if endpoint == "usage" else mock_get_spend_data
        mock_fetch.assert_called_once()
        passed_params = mock_fetch.call_args[0][1]
        self.assertEqual(json.loads(passed_params["team_ids"]), [self.team.pk])
        self.assertEqual(passed_params["teams_map"], {self.team.pk: self.team.name})

    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    @patch("ee.api.billing.posthog_feature_flag_enabled")
    def test_member_without_team_ids_gets_accessible_teams_injected(
        self, mock_flag_eval: MagicMock, mock_get_usage_data: MagicMock
    ):
        self._setup_member_with_private_team()
        mock_flag_eval.side_effect = self._member_access_flags
        mock_get_usage_data.return_value = self.MOCK_USAGE_DATA

        response = self.client.get("/api/billing/usage/?start_date=2025-01-01")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_get_usage_data.assert_called_once()
        passed_params = mock_get_usage_data.call_args[0][1]
        self.assertEqual(json.loads(passed_params["team_ids"]), [self.team.pk])
        self.assertEqual(passed_params["teams_map"], {self.team.pk: self.team.name})

    @parameterized.expand([("usage",), ("spend",)])
    @patch("ee.billing.billing_manager.BillingManager.get_spend_data")
    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    @patch("ee.api.billing.posthog_feature_flag_enabled")
    def test_member_requesting_only_inaccessible_teams_gets_403(
        self,
        endpoint: str,
        mock_flag_eval: MagicMock,
        mock_get_usage_data: MagicMock,
        mock_get_spend_data: MagicMock,
    ):
        private_team = self._setup_member_with_private_team()
        mock_flag_eval.side_effect = self._member_access_flags

        response = self.client.get(f"/api/billing/{endpoint}/?team_ids=[{private_team.pk}]")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # An empty team_ids list means "all teams" to the billing service, so it must never be called here
        mock_get_usage_data.assert_not_called()
        mock_get_spend_data.assert_not_called()

    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    @patch("ee.api.billing.posthog_feature_flag_enabled")
    def test_member_with_zero_accessible_teams_never_calls_billing(
        self, mock_flag_eval: MagicMock, mock_get_usage_data: MagicMock
    ):
        self._setup_member_with_private_team()
        self._make_team_private(self.team)
        mock_flag_eval.side_effect = self._member_access_flags

        response = self.client.get("/api/billing/usage/")

        # TeamMemberAccessPermission rejects a member whose current team is private; the in-view
        # zero-accessible-teams guard backstops it. Either way billing must never be called, since
        # an absent or empty team_ids means "all teams" to the billing service.
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_get_usage_data.assert_not_called()

    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    @patch("ee.api.billing.posthog_feature_flag_enabled")
    def test_member_response_team_id_options_filtered(self, mock_flag_eval: MagicMock, mock_get_usage_data: MagicMock):
        private_team = self._setup_member_with_private_team()
        mock_flag_eval.side_effect = self._member_access_flags
        deleted_team_id = 999999
        mock_get_usage_data.return_value = {
            "results": [{"data": [1, 2], "count": 2}],
            "team_id_options": [self.team.pk, private_team.pk, deleted_team_id],
        }

        response = self.client.get("/api/billing/usage/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["team_id_options"], [self.team.pk])
        self.assertEqual(data["results"], [{"data": [1, 2], "count": 2}])

    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    @patch("ee.api.billing.posthog_feature_flag_enabled")
    def test_member_scoping_does_not_depend_on_user_teams_first_org(
        self, mock_flag_eval: MagicMock, mock_get_usage_data: MagicMock
    ):
        private_team = self._setup_member_with_private_team()
        mock_flag_eval.side_effect = self._member_access_flags
        mock_get_usage_data.return_value = {
            "results": [],
            "team_id_options": [self.team.pk, private_team.pk],
        }

        # User.teams gates private-project filtering on the features of the user's *first* org.
        # Simulate the multi-org case where that first org lacks ACCESS_CONTROL, making User.teams
        # leak this org's private team: the endpoint must not use it as the security boundary.
        leaky_teams = Team.objects.filter(organization=self.organization)
        with patch.object(User, "teams", new_callable=PropertyMock, return_value=leaky_teams):
            response = self.client.get("/api/billing/usage/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_get_usage_data.assert_called_once()
        passed_params = mock_get_usage_data.call_args[0][1]
        self.assertEqual(json.loads(passed_params["team_ids"]), [self.team.pk])
        self.assertEqual(passed_params["teams_map"], {self.team.pk: self.team.name})
        self.assertEqual(response.json()["team_id_options"], [self.team.pk])

    @parameterized.expand([("not-json",), ('["a"]',)])
    @patch("ee.billing.billing_manager.BillingManager.get_usage_data")
    @patch("ee.api.billing.posthog_feature_flag_enabled")
    def test_member_malformed_team_ids_returns_400(
        self, raw_team_ids: str, mock_flag_eval: MagicMock, mock_get_usage_data: MagicMock
    ):
        self._setup_member_with_private_team()
        mock_flag_eval.side_effect = self._member_access_flags

        response = self.client.get(f"/api/billing/usage/?team_ids={raw_team_ids}")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_get_usage_data.assert_not_called()

    @parameterized.expand([("usage",), ("spend",)])
    def test_billing_service_permission_denied_returns_403(self, endpoint: str):
        # The billing service gates these endpoints on the same flags we do, from its own cache, so a
        # flag rollout can leave it denying a request we allowed. That must read as a permission
        # denial, not as a generic failure.
        with patch(f"ee.billing.billing_manager.BillingManager.get_{endpoint}_data") as mock_fetch:
            mock_fetch.side_effect = Exception(
                "Billing service returned bad status code: 403",
                "body:",
                {
                    "type": "authentication_error",
                    "code": "permission_denied",
                    "detail": "You do not have permission to perform this action.",
                    "attr": None,
                },
            )

            response = self.client.get(f"/api/billing/{endpoint}/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["detail"], HasBillingUsageSpendReadAccess.message)

    @parameterized.expand([("usage",), ("spend",)])
    def test_billing_service_other_error_still_returns_400(self, endpoint: str):
        with patch(f"ee.billing.billing_manager.BillingManager.get_{endpoint}_data") as mock_fetch:
            mock_fetch.side_effect = Exception(
                "Billing service returned bad status code: 400",
                "body:",
                {"code": "invalid_input", "error_message": "start_date is invalid"},
            )

            response = self.client.get(f"/api/billing/{endpoint}/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        self.assertEqual(data["code"], "invalid_input")
        self.assertEqual(data["detail"], "start_date is invalid")


class TestBillingPeriodAPI(APILicensedTest):
    def test_member_can_read_synced_organization_period(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.organization.usage = {
            "period": ["2026-07-09T00:00:00Z", "2026-08-09T00:00:00Z"],
        }
        self.organization.save()

        response = self.client.get("/api/billing/period/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "current_period_start": "2026-07-09T00:00:00Z",
                "current_period_end": "2026-08-09T00:00:00Z",
            },
        )

    def test_gateway_scoped_personal_api_key_can_read_team_period(self):
        self.organization.usage = {
            "period": ["2026-07-09T00:00:00Z", "2026-08-09T00:00:00Z"],
        }
        self.organization.save()
        self.client.logout()
        raw_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="billing-period-test",
            user=self.user,
            secure_value=hash_key_value(raw_key),
            scopes=["llm_gateway:read"],
            scoped_teams=[self.team.pk],
        )

        response = self.client.get(
            f"/api/billing/period/?team_id={self.team.pk}",
            headers={"authorization": f"Bearer {raw_key}"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["current_period_end"], "2026-08-09T00:00:00Z")


class TestBillingPermissionDeniedForMembers(APILicensedTest):
    """Verify that billing-modifying actions reject member-level users with 403."""

    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

    @parameterized.expand(
        [
            ("activate", "post", "/api/billing/activate", {"products": "all_products:"}),
            ("deactivate", "post", "/api/billing/deactivate", {"products": "product_1"}),
            ("patch", "patch", "/api/billing//", {"custom_limits_usd": {}}),
            ("subscription_switch_plan", "post", "/api/billing/subscription/switch-plan", {"plan": "test"}),
            ("portal", "get", "/api/billing/portal", None),
            ("activate_trial", "post", "/api/billing/trials/activate", {"product": "test"}),
            ("cancel_trial", "post", "/api/billing/trials/cancel", {"product": "test"}),
            ("purchase_credits", "post", "/api/billing/credits/purchase", {"amount": 100}),
            ("claim_coupon", "post", "/api/billing/coupons/claim", {"code": "TEST"}),
            ("startup_apply", "post", "/api/billing/startups/apply", "USE_ORG_ID"),
        ]
    )
    def test_permission_denied(self, _name, method, url, data):
        if data == "USE_ORG_ID":
            data = {"organization_id": str(self.organization.id)}
        client_method = getattr(self.client, method)
        if data is not None:
            kwargs = {"data": data}
            if method == "patch":
                kwargs["content_type"] = "application/json"
            response = client_method(url, **kwargs)
        else:
            response = client_method(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("ee.api.billing.requests.get")
    def test_list_still_accessible(self, mock_request):
        # Session-authenticated members can still read the historical billing overview payload.
        # MCP/token reads are separately gated by billing access.
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = create_billing_response(
            customer=create_billing_customer(),
        )

        response = self.client.get("/api/billing")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_get_invoices_still_accessible(self):
        response = self.client.get("/api/billing/get_invoices")
        self.assertIn(
            response.status_code, [status.HTTP_200_OK, status.HTTP_301_MOVED_PERMANENTLY, status.HTTP_302_FOUND]
        )

    def test_credits_overview_still_accessible(self):
        response = self.client.get("/api/billing/credits/overview")
        self.assertIn(
            response.status_code, [status.HTTP_200_OK, status.HTTP_301_MOVED_PERMANENTLY, status.HTTP_302_FOUND]
        )

    def test_coupons_overview_still_accessible(self):
        response = self.client.get("/api/billing/coupons/overview")
        self.assertIn(
            response.status_code, [status.HTTP_200_OK, status.HTTP_301_MOVED_PERMANENTLY, status.HTTP_302_FOUND]
        )
