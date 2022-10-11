from datetime import datetime
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import jwt
import pytz
from freezegun import freeze_time
from rest_framework import status

from ee.api.test.base import APILicensedTest
from ee.models.license import License


def create_billing_response(**kwargs) -> Dict[str, Any]:
    data: Any = {"stripe_portal_url": None, "products": None, "custom_limits_usd": {}}
    data.update(kwargs)
    return data


def create_missing_billing_customer(**kwargs) -> Dict[str, Any]:
    data: Any = {"custom_limits_usd": {}, "has_active_subscription": False}
    data.update(kwargs)
    return data


def create_billing_customer(**kwargs) -> Dict[str, Any]:
    data: Any = {
        "custom_limits_usd": {},
        "has_active_subscription": True,
        "stripe_portal_url": "https://billing.stripe.com/p/session/test_1234",
        "current_total_amount_usd": "100.00",
        "products": [
            {
                "name": "Product OS",
                "description": "Product Analytics, event pipelines, data warehousing",
                "price_description": None,
                "type": "EVENTS",
                "free_allocation": 10000,
                "tiers": [
                    {"unit_amount_usd": "0.00", "up_to": 1000000, "current_amount_usd": "0.00"},
                    {"unit_amount_usd": "0.00045", "up_to": 2000000, "current_amount_usd": None},
                ],
                "current_amount_usd": "0.00",
                "current_usage": 0,
                "usage_limit": None,
                "has_exceeded_limit": False,
            }
        ],
        "billing_period": {"current_period_start": "2022-10-07T11:12:48", "current_period_end": "2022-11-07T11:12:48"},
    }
    data.update(kwargs)
    return data


def create_billing_products_response(**kwargs) -> Dict[str, Any]:
    data: Any = {
        "products": [
            {
                "name": "Product OS",
                "description": "Product Analytics, event pipelines, data warehousing",
                "price_description": None,
                "type": "EVENTS",
                "free_allocation": 10000,
                "tiers": [
                    {"unit_amount_usd": "0.00", "up_to": 1000000, "current_amount_usd": "0.00"},
                    {"unit_amount_usd": "0.00045", "up_to": 2000000, "current_amount_usd": None},
                ],
            }
        ],
    }
    data.update(kwargs)
    return data


def create_billing_license_response(**kwargs) -> Dict[str, Any]:
    data: Any = {
        "license": [
            {
                "name": "Product OS",
                "description": "Product Analytics, event pipelines, data warehousing",
                "price_description": None,
                "type": "EVENTS",
                "free_allocation": 10000,
                "tiers": [
                    {"unit_amount_usd": "0.00", "up_to": 1000000, "current_amount_usd": "0.00"},
                    {"unit_amount_usd": "0.00045", "up_to": 2000000, "current_amount_usd": None},
                ],
            }
        ],
    }
    data.update(kwargs)
    return data


class TestBillingAPI(APILicensedTest):
    @patch("ee.api.billing.requests.get")
    @freeze_time("2022-01-01")
    def test_billing_v2_calls_the_service_with_appropriate_token(self, mock_request):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = create_billing_response()

        self.client.get("/api/billing-v2")
        assert mock_request.call_args.args[0] == "http://localhost:8100/api/billing"
        token = mock_request.call_args.kwargs["headers"]["Authorization"].split(" ")[1]

        secret = self.license.key.split("::")[1]

        decoded_token = jwt.decode(
            token, secret, algorithms=["HS256"], audience="posthog:license-key", options={"verify_aud": True}
        )

        assert decoded_token == {
            "aud": "posthog:license-key",
            "exp": 1640996100,
            "id": self.license.key.split("::")[0],
            "organization_id": str(self.organization.id),
        }

    @patch("ee.api.billing.requests.get")
    def test_billing_v2_returns_404_by_default(self, mock_request):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = create_billing_response()

        response = self.client.get("/api/billing-v2")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("ee.api.billing.requests.get")
    def test_billing_v2_returns_if_billing_exists(self, mock_request):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = create_billing_response(customer=create_billing_customer())
        response = self.client.get("/api/billing-v2")
        assert response.status_code == status.HTTP_200_OK

        assert response.json() == create_billing_customer()

    @patch("ee.api.billing.requests.get")
    def test_billing_v2_returns_if_doesnt_exist_but_enabled_for_instance(self, mock_request):
        def mock_implementation(url: str, headers: Any = None) -> MagicMock:
            mock = MagicMock()
            mock.status_code = 404

            if "api/billing" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_response(customer=create_missing_billing_customer())
            if "api/products" in url:
                mock.status_code = 200
                mock.json.return_value = create_billing_products_response()

            return mock

        mock_request.side_effect = mock_implementation

        with self.settings(BILLING_V2_ENABLED=True):
            response = self.client.get("/api/billing-v2")
            assert response.status_code == status.HTTP_200_OK
            assert response.json() == {
                "custom_limits_usd": {},
                "has_active_subscription": False,
                "products": [
                    {
                        "name": "Product OS",
                        "description": "Product Analytics, event pipelines, data warehousing",
                        "price_description": None,
                        "type": "EVENTS",
                        "free_allocation": 10000,
                        "tiers": [
                            {"unit_amount_usd": "0.00", "up_to": 1000000, "current_amount_usd": "0.00"},
                            {"unit_amount_usd": "0.00045", "up_to": 2000000, "current_amount_usd": None},
                        ],
                        "current_usage": 0,
                    }
                ],
            }

    @patch("ee.api.billing.requests.get")
    def test_billing_stores_valid_license(self, mock_request):
        self.license.delete()

        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {
            "license": {
                "valid_until": "2100-01-01T00:00:00Z",
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

    @patch("ee.api.billing.requests.get")
    def test_license_is_updated_on_billing_load(self, mock_request):
        mock_request.return_value.status_code = 200
        mock_request.return_value.json.return_value = {
            "license": {
                "valid_until": "2100-01-01T00:00:00Z",
                "type": "scale",
            }
        }

        assert self.license.plan == "enterprise"
        self.client.get("/api/billing-v2")
        self.license.refresh_from_db()
        assert self.license.plan == "scale"

        mock_request.return_value.json.return_value = {
            "license": {
                "valid_until": "2200-01-01T00:00:00Z",
                "type": "enterprise",
            }
        }

        self.client.get("/api/billing-v2")
        self.license.refresh_from_db()
        assert self.license.plan == "enterprise"
        assert self.license.valid_until == datetime(2200, 1, 1, 0, 0, 0, tzinfo=pytz.UTC)
