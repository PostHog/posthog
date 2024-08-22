from django.conf import settings
from datetime import datetime, timedelta, UTC
from django.db.models import F
from enum import Enum
from typing import Any, Optional, cast

import jwt
import requests
import structlog
from sentry_sdk import capture_message
from requests import JSONDecodeError  # type: ignore[attr-defined]
from rest_framework.exceptions import NotAuthenticated
from sentry_sdk import capture_exception

from ee.billing.billing_types import BillingStatus
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
            "exp": datetime.now(UTC) + timedelta(minutes=15),
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

            response["stripe_portal_url"] = f"{settings.SITE_URL}/api/billing/portal"

            # Extend the products with accurate usage_limit info
            for product in response["products"]:
                usage_key = product.get("usage_key")
                if not usage_key:
                    continue
                usage = response.get("usage_summary", {}).get(usage_key, {})
                usage_limit = usage.get("limit")
                billing_reported_usage = usage.get("usage") or 0
                current_usage = billing_reported_usage

                product_usage: dict[str, Any] = {}
                if organization and organization.usage:
                    product_usage = organization.usage.get(usage_key) or {}

                if product_usage.get("todays_usage"):
                    todays_usage = product_usage["todays_usage"]
                    current_usage = billing_reported_usage + todays_usage

                product["current_usage"] = current_usage
                product["percentage_usage"] = current_usage / usage_limit if usage_limit else 0
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

    def update_billing_organization_users(self, organization: Organization) -> None:
        try:
            distinct_ids = list(organization.members.values_list("distinct_id", flat=True))

            first_owner_membership = (
                OrganizationMembership.objects.filter(organization=organization, level=15)
                .order_by("-joined_at")
                .first()
            )
            if not first_owner_membership:
                capture_message(f"No owner membership found for organization {organization.id}")
                return
            first_owner = first_owner_membership.user

            admin_emails = list(
                organization.members.filter(
                    organization_membership__level__gte=OrganizationMembership.Level.ADMIN
                ).values_list("email", flat=True)
            )

            org_users = list(
                organization.members.values(
                    "email",
                    "distinct_id",
                    "organization_membership__level",
                )
                .annotate(role=F("organization_membership__level"))
                .filter(role__gte=OrganizationMembership.Level.ADMIN)
                .values(
                    "email",
                    "distinct_id",
                    "role",
                )
            )

            self.update_billing(
                organization,
                {
                    "distinct_ids": distinct_ids,
                    "org_customer_email": first_owner.email,
                    "org_admin_emails": admin_emails,
                    "org_users": org_users,
                },
            )
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

        if not self.license.valid_until or self.license.valid_until < datetime.now(UTC) + timedelta(days=29):
            # NOTE: License validity is a legacy concept. For now we always extend the license validity by 30 days.
            self.license.valid_until = datetime.now(UTC) + timedelta(days=30)
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

    def _get_stripe_portal_url(self, organization: Organization) -> str:
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
                rows_synced=usage_summary.get("rows_synced", {}),
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
