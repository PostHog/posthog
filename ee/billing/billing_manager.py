from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Optional, Union, cast

import jwt
import requests
import structlog
from django.utils import timezone
from requests import JSONDecodeError  # type: ignore[attr-defined]
from rest_framework.exceptions import NotAuthenticated
from sentry_sdk import capture_exception

from ee.billing.billing_types import BillingStatus, Tier
from ee.billing.quota_limiting import set_org_usage_summary, sync_org_quota_limits
from ee.models import License
from ee.settings import BILLING_SERVICE_URL
from posthog.cloud_utils import get_cached_instance_license
from posthog.models import Organization
from posthog.models.organization import OrganizationMembership, OrganizationUsageInfo

logger = structlog.get_logger(__name__)


class BillingAPIErrorCodes(Enum):
    OPEN_INVOICES_ERROR = "open_invoices_error"


def build_billing_token(license: License, organization: Organization):
    if not organization or not license:
        raise NotAuthenticated()

    license_id = license.key.split("::")[0]
    license_secret = license.key.split("::")[1]

    encoded_jwt = jwt.encode(
        {
            "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=15),
            "id": license_id,
            "organization_id": str(organization.id),
            "organization_name": organization.name,
            "aud": "posthog:license-key",
        },
        license_secret,
        algorithm="HS256",
    )

    return encoded_jwt


def handle_billing_service_error(res: requests.Response, valid_codes=(200, 404, 401)) -> None:
    if res.status_code not in valid_codes:
        logger.error(f"Billing service returned bad status code: {res.status_code}, body: {res.text}")
        try:
            response = res.json()
            raise Exception(f"Billing service returned bad status code: {res.status_code}", f"body:", response)
        except JSONDecodeError:
            raise Exception(f"Billing service returned bad status code: {res.status_code}", f"body:", res.text)


def compute_usage_per_tier(current_usage: int, projected_usage: int, tiers, limit):
    remaining_usage = current_usage
    limited_remaining_usage = limit or current_usage
    remaining_projected_usage = projected_usage or 0
    previous_tier: Optional[dict[str, Any]] = None
    tier_max_usage: Union[int, float] = 0

    result: list[Tier] = []
    for tier in tiers:
        if previous_tier and previous_tier.get("up_to"):
            previous_tier_up_to = previous_tier["up_to"]
        else:
            previous_tier_up_to = 0

        if tier.get("up_to"):
            tier_max_usage = tier["up_to"] - previous_tier_up_to
        else:
            tier_max_usage = float("inf")

        flat_amount_usd = Decimal(tier.get("flat_amount_usd") or 0)
        unit_amount_usd = Decimal(tier.get("unit_amount_usd") or 0)
        usage_this_tier = int(min(remaining_usage, tier_max_usage))
        limited_usage_this_tier = int(min(limited_remaining_usage, tier_max_usage))
        limited_remaining_usage -= usage_this_tier
        limited_remaining_usage = max(limited_remaining_usage, 0)
        remaining_usage -= usage_this_tier
        current_amount_usd = Decimal(unit_amount_usd * limited_usage_this_tier + flat_amount_usd).quantize(
            Decimal("0.01")
        )
        previous_tier = tier
        if projected_usage:
            projected_usage_this_tier = int(min(remaining_projected_usage, tier_max_usage))
            remaining_projected_usage -= projected_usage_this_tier
            projected_amount_usd = Decimal(unit_amount_usd * projected_usage_this_tier + flat_amount_usd).quantize(
                Decimal("0.01")
            )
        else:
            projected_usage_this_tier = None
            projected_amount_usd = None

        result.append(
            Tier(
                flat_amount_usd=str(flat_amount_usd),
                unit_amount_usd=str(unit_amount_usd),
                up_to=tier.get("up_to", None),
                current_amount_usd=str(current_amount_usd),
                current_usage=usage_this_tier,
                projected_usage=projected_usage_this_tier,
                projected_amount_usd=str(projected_amount_usd),
            )
        )
    return result


def sum_total_across_tiers(tiers):
    total = Decimal(0)
    for tier in tiers:
        total += Decimal(tier["current_amount_usd"])
    return total


class BillingManager:
    license: Optional[License]

    def __init__(self, license):
        self.license = license or get_cached_instance_license()

    def get_billing(self, organization: Optional[Organization], plan_keys: Optional[str]) -> dict[str, Any]:
        if organization and self.license and self.license.is_v2_license:
            billing_service_response = self._get_billing(organization)

            # Ensure the license and org are updated with the latest info
            if billing_service_response.get("license"):
                self.update_license_details(billing_service_response)

            if organization and billing_service_response:
                self.update_org_details(organization, billing_service_response)

            response: dict[str, Any] = {"available_product_features": []}

            response["license"] = {"plan": self.license.plan}

            if organization and billing_service_response.get("customer"):
                response.update(billing_service_response["customer"])

            if not billing_service_response["customer"].get("products"):
                products = self.get_default_products(organization)
                response["products"] = products["products"]

            stripe_portal_url = self._get_stripe_portal_url(organization)
            response["stripe_portal_url"] = stripe_portal_url

            # Extend the products with accurate usage_limit info
            for product in response["products"]:
                usage_key = product.get("usage_key", None)
                if not usage_key:
                    continue
                usage = response.get("usage_summary", {}).get(usage_key, {})
                usage_limit = usage.get("limit")
                current_usage = usage.get("usage") or 0

                if (
                    organization
                    and organization.usage
                    and organization.usage.get(usage_key, {}).get("todays_usage", None)
                ):
                    todays_usage = organization.usage[usage_key]["todays_usage"]
                    current_usage = current_usage + todays_usage

                product["current_usage"] = current_usage
                product["percentage_usage"] = current_usage / usage_limit if usage_limit else 0

                # Also update the tiers
                if product.get("tiers"):
                    product["tiers"] = compute_usage_per_tier(
                        current_usage,
                        product["projected_usage"],
                        product["tiers"],
                        organization.usage[usage_key]["limit"],
                    )
                    product["current_amount_usd"] = sum_total_across_tiers(product["tiers"])

                # Update the add on tiers
                # TODO: enhanced_persons: make sure this updates properly for addons with different usage keys
                for addon in product.get("addons"):
                    if not addon.get("subscribed"):
                        continue
                    addon_usage_key = addon.get("usage_key")
                    if not usage_key:
                        continue
                    if addon_usage_key != usage_key:
                        usage = response.get("usage_summary", {}).get(addon_usage_key, {})
                        usage_limit = usage.get("limit")
                        current_usage = usage.get("usage") or 0
                        if (
                            organization
                            and organization.usage
                            and organization.usage.get(usage_key, {}).get("todays_usage", None)
                        ):
                            todays_usage = organization.usage[usage_key]["todays_usage"]
                            current_usage = current_usage + todays_usage
                    addon["current_usage"] = current_usage
                    addon["tiers"] = compute_usage_per_tier(
                        current_usage, addon["projected_usage"], addon["tiers"], organization.usage[usage_key]["limit"]
                    )
                    addon["current_amount_usd"] = sum_total_across_tiers(addon["tiers"])
        else:
            products = self.get_default_products(organization)
            response = {
                "available_product_features": [],
                "products": products["products"],
            }

        return response

    def update_billing(self, organization: Organization, data: dict[str, Any]) -> None:
        res = requests.patch(
            f"{BILLING_SERVICE_URL}/api/billing/",
            headers=self.get_auth_headers(organization),
            json=data,
        )

        handle_billing_service_error(res)

    def update_billing_distinct_ids(self, organization: Organization) -> None:
        distinct_ids = list(organization.members.values_list("distinct_id", flat=True))
        self.update_billing(organization, {"distinct_ids": distinct_ids})

    def update_billing_customer_email(self, organization: Organization) -> None:
        try:
            owner_membership = OrganizationMembership.objects.get(organization=organization, level=15)
            user = owner_membership.user
            self.update_billing(organization, {"org_customer_email": user.email})
        except Exception as e:
            capture_exception(e)

    def update_billing_admin_emails(self, organization: Organization) -> None:
        try:
            admin_emails = list(
                organization.members.filter(
                    organization_membership__level__gte=OrganizationMembership.Level.ADMIN
                ).values_list("email", flat=True)
            )
            self.update_billing(organization, {"org_admin_emails": admin_emails})
        except Exception as e:
            capture_exception(e)

    def deactivate_products(self, organization: Organization, products: str) -> None:
        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/billing/deactivate?products={products}",
            headers=self.get_auth_headers(organization),
        )

        handle_billing_service_error(res)

    def get_default_products(self, organization: Optional[Organization]) -> dict:
        response = {}
        # If we don't have products from the billing service then get the default ones with our local usage calculation
        products = self._get_products(organization)
        response["products"] = products

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

        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/billing",
            headers=self.get_auth_headers(organization),
        )
        handle_billing_service_error(res)

        data = res.json()

        return data

    def _get_stripe_portal_url(self, organization: Organization) -> BillingStatus:
        """
        Retrieves stripe protal url
        """
        if not self.license:  # mypy
            raise Exception("No license found")

        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/billing/portal",
            headers=self.get_auth_headers(organization),
        )

        handle_billing_service_error(res)

        data = res.json()

        return data["url"]

    def _get_products(self, organization: Optional[Organization]):
        headers = {}
        params = {"plan": "standard"}

        if self.license and organization:
            headers = self.get_auth_headers(organization)

        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/products-v2",
            params=params,
            headers=headers,
        )

        handle_billing_service_error(res)

        return res.json().get("products", [])

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
            usage_info = OrganizationUsageInfo(
                events=usage_summary["events"],
                recordings=usage_summary["recordings"],
                rows_synced=usage_summary.get("rows_synced", None),
                period=[
                    data["billing_period"]["current_period_start"],
                    data["billing_period"]["current_period_end"],
                ],
            )

            if set_org_usage_summary(organization, new_usage=usage_info):
                org_modified = True
                sync_org_quota_limits(organization)

        available_product_features = data.get("available_product_features", None)
        if available_product_features and available_product_features != organization.available_product_features:
            organization.available_product_features = data["available_product_features"]
            org_modified = True

        never_drop_data = data.get("never_drop_data", None)
        if never_drop_data != organization.never_drop_data:
            organization.never_drop_data = never_drop_data
            org_modified = True

        customer_trust_scores = data.get("customer_trust_scores", {})

        product_key_to_usage_key = {
            product["type"]: product["usage_key"]
            for product in (
                billing_status["customer"].get("products") or self.get_default_products(organization)["products"]
            )
        }
        org_customer_trust_scores = {}
        for product_key in customer_trust_scores:
            if product_key in product_key_to_usage_key:
                org_customer_trust_scores[product_key_to_usage_key[product_key]] = customer_trust_scores[product_key]

        if org_customer_trust_scores != organization.customer_trust_scores:
            organization.customer_trust_scores.update(org_customer_trust_scores)
            org_modified = True

        if org_modified:
            organization.save()

        return organization

    def get_auth_headers(self, organization: Organization):
        if not self.license:  # mypy
            raise Exception("No license found")
        billing_service_token = build_billing_token(self.license, organization)
        return {"Authorization": f"Bearer {billing_service_token}"}

    def get_invoices(self, organization: Organization, status: Optional[str]):
        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/billing/get_invoices",
            params={"status": status},
            headers=self.get_auth_headers(organization),
        )

        handle_billing_service_error(res)

        data = res.json()

        return data
