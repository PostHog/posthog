import calendar
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple, TypedDict

import jwt
import pytz
import requests
import structlog
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework.exceptions import NotAuthenticated

from ee.models import License
from ee.settings import BILLING_SERVICE_URL
from posthog.cloud_utils import is_cloud
from posthog.constants import AvailableFeature
from posthog.models import Organization
from posthog.models.event.util import get_event_count_for_team_and_period
from posthog.models.organization import OrganizationUsageInfo
from posthog.models.session_recording_event.util import get_recording_count_for_team_and_period
from posthog.models.team.team import Team
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
    current_period_start: timezone.datetime
    current_period_end: timezone.datetime


class CustomerInfo(TypedDict):
    customer_id: Optional[str]
    deactivated: bool
    has_active_subscription: bool
    stripe_portal_url: str
    available_features: List[AvailableFeature]
    current_total_amount_usd: Optional[str]
    products: Optional[List[CustomerProduct]]
    custom_limits_usd: Optional[Dict[str, str]]
    billing_period: Optional[BillingPeriod]
    last_reported_usage: Optional[Dict[str, int]]
    free_trial_until: Optional[timezone.datetime]


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


def get_this_month_date_range() -> Tuple[datetime, datetime]:
    now = datetime.utcnow()
    date_range: Tuple[int, int] = calendar.monthrange(now.year, now.month)
    start_time: datetime = datetime.combine(
        datetime(now.year, now.month, 1),
        time.min,
    ).replace(tzinfo=pytz.UTC)

    end_time: datetime = datetime.combine(
        datetime(now.year, now.month, date_range[1]),
        time.max,
    ).replace(tzinfo=pytz.UTC)

    return (start_time, end_time)


def handle_billing_service_error(res: requests.Response, valid_codes=(200, 404, 401)) -> None:
    if res.status_code not in valid_codes:
        logger.error(f"Billing service returned bad status code: {res.status_code}, body: {res.text}")
        raise Exception(f"Billing service returned bad status code: {res.status_code}")


class BillingManager:
    license: Optional[License]

    def __init__(self, license):
        self.license = license or License.objects.first_valid()

    def get_billing(self, organization: Optional[Organization], plan_keys: Optional[str]) -> Dict[str, Any]:
        billing_service_response: Dict[str, Any] = {}

        # Get the specified plans from "plan_keys" query param, otherwise get the defaults
        plans = self._get_plans(plan_keys)
        if organization and self.license and self.license.is_v2_license:
            billing_service_response: BillingStatus = self._get_billing(organization)

            if not self.license:  # mypy
                raise Exception("No license found")

            # Ensure the license and org are updated with the latest info
            if billing_service_response.get("license"):
                self.update_license_details(billing_service_response)
            if organization:
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
            return response
        else:
            products = self.get_default_products(organization)
            return {
                "available_features": [],
                "available_plans": plans["plans"],
                "products": products["products"],
                "products_enterprise": products["products_enterprise"],
            }

    def update_billing(self, organization: Organization, data: Dict[str, Any]) -> None:
        if not self.license:  # mypy
            raise Exception("No license found")

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

        calculated_usage = self._get_cached_current_usage(organization) if organization else None

        for product in response["products"] + response["products_enterprise"]:
            if calculated_usage and product["type"] in calculated_usage:
                product["current_usage"] = calculated_usage[product["type"]]
            else:
                product["current_usage"] = 0

        for product in response["products"]:
            usage_limit = product.get("usage_limit", product.get("free_allocation"))
            product["percentage_usage"] = product["current_usage"] / usage_limit if usage_limit else 0

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

        org_usage: Dict[str, OrganizationUsageInfo] = {
            "events": {
                "usage": None,
                "limit": None,
            },
            "recordings": {
                "usage": None,
                "limit": None,
            },
            "period": data["billing_period"],
        }

        if data.get("has_active_subscription"):
            # If we have a subscription use the correct values from there
            for product in data["products"]:
                if product["type"] in org_usage:
                    org_usage[product["type"]]["usage"] = product["current_usage"]
                    org_usage[product["type"]]["limit"] = product.get("usage_limit")
        else:
            # If we have a subscription use the correct values from there
            for key in data["last_reported_usage"].keys():
                if key in org_usage:
                    org_usage[key]["usage"] = data["last_reported_usage"][key]

        if org_usage and org_usage != organization.usage:
            organization.usage = org_usage
            org_modified = True

        available_features = data.get("available_features", None)
        if available_features and available_features != organization.available_features:
            organization.available_features = data["available_features"]
            org_modified = True

        if org_modified:
            organization.save()

        return organization

    def _get_cached_current_usage(self, organization: Organization) -> Dict[str, int]:
        """
        Calculate the actual current usage for an organization - only used if a subscription does not exist
        """
        cache_key: str = f"monthly_usage_breakdown_{organization.id}"
        usage: Optional[Dict[str, int]] = cache.get(cache_key)

        # TODO BW: For self-hosted this should be priced across all orgs

        if usage is None:
            teams = Team.objects.filter(organization=organization).exclude(organization__for_internal_metrics=True)

            usage = {
                "events": 0,
                "recordings": 0,
            }

            (start_period, end_period) = get_this_month_date_range()

            for team in teams:
                if not team.is_demo:
                    usage["recordings"] += get_recording_count_for_team_and_period(team.id, start_period, end_period)
                    usage["events"] += get_event_count_for_team_and_period(team.id, start_period, end_period)

            cache.set(
                cache_key,
                usage,
                min(
                    settings.BILLING_USAGE_CACHING_TTL,
                    (end_period - timezone.now()).total_seconds(),
                ),
            )

        return usage

    def get_auth_headers(self, organization: Organization):
        billing_service_token = build_billing_token(self.license, organization)
        return {"Authorization": f"Bearer {billing_service_token}"}
