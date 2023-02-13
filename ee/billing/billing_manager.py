from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, TypedDict, cast

import jwt
import requests
import structlog
from django.utils import timezone
from rest_framework.exceptions import NotAuthenticated

from ee.models import License
from ee.settings import BILLING_SERVICE_URL
from posthog.cloud_utils import is_cloud
from posthog.constants import AvailableFeature
from posthog.models import Organization
from posthog.models.organization import OrganizationUsageInfo
from posthog.models.user import User

logger = structlog.get_logger(__name__)


class Tier(TypedDict):
    flat_amount_usd: Decimal
    unit_amount_usd: Decimal
    current_amount_usd: Decimal
    up_to: Optional[int]


class CustomerProduct(TypedDict):
    name: str
    description: str
    price_description: Optional[str]
    image_url: Optional[str]
    type: str
    free_allocation: int
    tiers: List[Tier]
    tiered: bool
    unit_amount_usd: Optional[Decimal]
    current_amount_usd: Decimal
    current_usage: int
    usage_limit: Optional[int]
    has_exceeded_limit: bool
    percentage_usage: float
    projected_usage: int
    projected_amount: Decimal


class LicenseInfo(TypedDict):
    type: str


class BillingPeriod(TypedDict):
    current_period_start: str
    current_period_end: str


class UsageSummary(TypedDict):
    limit: Optional[int]
    usage: Optional[int]


class CustomerInfo(TypedDict):
    customer_id: Optional[str]
    deactivated: bool
    has_active_subscription: bool
    stripe_portal_url: str
    billing_period: BillingPeriod
    available_features: List[AvailableFeature]
    current_total_amount_usd: Optional[str]
    products: Optional[List[CustomerProduct]]
    custom_limits_usd: Optional[Dict[str, str]]
    free_trial_until: Optional[str]
    usage_summary: Dict[str, UsageSummary]


class BillingStatus(TypedDict):
    license: LicenseInfo
    customer: CustomerInfo


def build_billing_token(license: License, organization: Organization):
    if not organization or not license:
        raise NotAuthenticated()

    license_id = license.key.split("::")[0]
    license_secret = license.key.split("::")[1]

    distinct_ids = []
    if is_cloud():
        distinct_ids = list(organization.members.values_list("distinct_id", flat=True))
    else:
        distinct_ids = list(User.objects.values_list("distinct_id", flat=True))

    encoded_jwt = jwt.encode(
        {
            "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=15),
            "id": license_id,
            "organization_id": str(organization.id),
            "organization_name": organization.name,
            "distinct_ids": distinct_ids,
            "aud": "posthog:license-key",
        },
        license_secret,
        algorithm="HS256",
    )

    return encoded_jwt


def handle_billing_service_error(res: requests.Response, valid_codes=(200, 404, 401)) -> None:
    if res.status_code not in valid_codes:
        logger.error(f"Billing service returned bad status code: {res.status_code}, body: {res.text}")
        raise Exception(f"Billing service returned bad status code: {res.status_code}")


class BillingManager:
    license: Optional[License]

    def __init__(self, license):
        self.license = license or License.objects.first_valid()

    def get_billing(self, organization: Optional[Organization], plan_keys: Optional[str]) -> Dict[str, Any]:
        # Get the specified plans from "plan_keys" query param, otherwise get the defaults
        plans = self._get_plans(plan_keys)
        if organization and self.license and self.license.is_v2_license:
            billing_service_response = self._get_billing(organization)

            # Ensure the license and org are updated with the latest info
            if billing_service_response.get("license"):
                self.update_license_details(billing_service_response)
            if organization and billing_service_response:
                self.update_org_details(organization, billing_service_response)

            response: Dict[str, Any] = {"available_features": []}

            response["license"] = {"plan": self.license.plan}

            if organization and billing_service_response.get("customer"):
                response.update(billing_service_response["customer"])

            if not billing_service_response["customer"].get("products"):
                products = self.get_default_products(organization)
                response["products"] = products["products"]
                response["products_enterprise"] = products["products_enterprise"]

            response["available_plans"] = plans["plans"]
        else:
            products = self.get_default_products(organization)
            response = {
                "available_features": [],
                "available_plans": plans["plans"],
                "products": products["products"],
                "products_enterprise": products["products_enterprise"],
            }

        # Extend the products with accurate usage_limit info

        for product in response["products"]:
            usage = response.get("usage_summary", {}).get(product["type"], {})
            usage_limit = usage.get("limit")
            current_usage = usage.get("usage") or 0

            if (
                organization
                and organization.usage
                and organization.usage.get(product["type"], {}).get("todays_usage", None)
            ):
                todays_usage = organization.usage[product["type"]]["todays_usage"]
                current_usage = current_usage + todays_usage

            product["current_usage"] = current_usage
            product["percentage_usage"] = current_usage / usage_limit if usage_limit else 0

        return response

    def update_billing(self, organization: Organization, data: Dict[str, Any]) -> None:
        res = requests.patch(
            f"{BILLING_SERVICE_URL}/api/billing/",
            headers=self.get_auth_headers(organization),
            json=data,
        )

        handle_billing_service_error(res)

    def get_default_products(self, organization: Optional[Organization]):
        response = {}
        # If we don't have products from the billing service then get the default ones with our local usage calculation
        products = self._get_products(organization)
        response["products"] = products["standard"]
        response["products_enterprise"] = products["enterprise"]

        return response

    def update_license_details(self, billing_status: BillingStatus) -> License:
        """
        Ensure the license details are up-to-date locally
        """
        if not self.license:  # mypy
            raise Exception("No license found")

        license_modified = False

        data = billing_status["license"]

        if not self.license.valid_until or self.license.valid_until < timezone.now() + timedelta(days=29):
            # NOTE: License validity is a legacy concept. For now we always extend the license validity by 30 days.
            self.license.valid_until = timezone.now() + timedelta(days=30)
            license_modified = True

        if self.license.plan != data["type"]:
            self.license.plan = data["type"]
            license_modified = True

        if license_modified:
            self.license.save()

        return self.license

    def _get_billing(self, organization: Organization) -> BillingStatus:
        """
        Retrieves billing info and updates local models if necessary
        """
        if not self.license:  # mypy
            raise Exception("No license found")

        res = requests.get(f"{BILLING_SERVICE_URL}/api/billing", headers=self.get_auth_headers(organization))

        handle_billing_service_error(res)

        data = res.json()

        return data

    def _get_plans(self, plan_keys: Optional[str]):
        res = requests.get(
            f'{BILLING_SERVICE_URL}/api/plans{"?keys=" + plan_keys if plan_keys else ""}',
        )

        handle_billing_service_error(res)

        return res.json()

    def _get_products(self, organization: Optional[Organization]):
        headers = {}
        params = {"plan": "standard"}

        if self.license and organization:
            headers = self.get_auth_headers(organization)

        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/products",
            params=params,
            headers=headers,
        )

        handle_billing_service_error(res)

        return res.json()

    def update_org_details(self, organization: Organization, billing_status: BillingStatus) -> Organization:
        """
        Ensure the relevant organization details are up-to-date locally
        """
        org_modified = False

        data = billing_status["customer"]

        if data.get("customer_id") and organization.customer_id != data["customer_id"]:
            organization.customer_id = data["customer_id"]
            org_modified = True

        usage_summary = cast(dict, data.get("usage_summary"))
        if usage_summary:
            # TRICKY: We don't want to overwrite the "todays_usage" value unless the
            # usage from the billing service is different than what we have locally.

            new_org_usage = OrganizationUsageInfo(
                events={
                    "usage": usage_summary["events"]["usage"],
                    "limit": usage_summary["events"]["limit"],
                    "todays_usage": organization.usage["events"].get("todays_usage", 0)
                    if organization.usage and usage_summary["events"]["usage"] == organization.usage["events"]["usage"]
                    else 0,
                },
                recordings={
                    "usage": usage_summary["recordings"]["usage"],
                    "limit": usage_summary["recordings"]["limit"],
                    "todays_usage": organization.usage["recordings"].get("todays_usage", 0)
                    if organization.usage
                    and usage_summary["recordings"]["usage"] == organization.usage["recordings"]["usage"]
                    else 0,
                },
                period=[
                    data["billing_period"]["current_period_start"],
                    data["billing_period"]["current_period_end"],
                ],
            )

            organization.usage = new_org_usage
            org_modified = True

        available_features = data.get("available_features", None)
        if available_features and available_features != organization.available_features:
            organization.available_features = data["available_features"]
            org_modified = True

        if org_modified:
            organization.save()

        return organization

    def get_auth_headers(self, organization: Organization):
        if not self.license:  # mypy
            raise Exception("No license found")
        billing_service_token = build_billing_token(self.license, organization)
        return {"Authorization": f"Bearer {billing_service_token}"}
