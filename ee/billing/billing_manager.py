from datetime import datetime, timedelta, UTC
from enum import Enum
from typing import Any, Optional, cast

import jwt
import requests
import structlog
from django.conf import settings
from django.db.models import F
from django.utils import timezone
from requests import JSONDecodeError
from rest_framework.exceptions import NotAuthenticated

from ee.billing.billing_types import BillingStatus
from ee.billing.quota_limiting import set_org_usage_summary, update_org_billing_quotas
from ee.models import License
from ee.settings import BILLING_SERVICE_URL
from posthog.cloud_utils import get_cached_instance_license
from posthog.exceptions_capture import capture_exception
from posthog.models import Organization
from posthog.models.organization import OrganizationMembership, OrganizationUsageInfo
from posthog.models.user import User

logger = structlog.get_logger(__name__)


class BillingAPIErrorCodes(Enum):
    OPEN_INVOICES_ERROR = "open_invoices_error"


def build_billing_token(license: License, organization: Organization, user: Optional[User] = None):
    if not organization or not license:
        raise NotAuthenticated()

    license_id = license.key.split("::")[0]
    license_secret = license.key.split("::")[1]

    payload = {
        "exp": datetime.now(tz=UTC) + timedelta(minutes=15),
        "id": license_id,
        "organization_id": str(organization.id),
        "organization_name": organization.name,
        "aud": "posthog:license-key",
    }

    if user:
        payload["distinct_id"] = str(user.distinct_id)

    encoded_jwt = jwt.encode(
        payload,
        license_secret,
        algorithm="HS256",
    )

    return encoded_jwt


def handle_billing_service_error(res: requests.Response, valid_codes=(200, 201, 404, 401)) -> None:
    if res.status_code not in valid_codes:
        logger.error(f"Billing service returned bad status code: {res.status_code}, body: {res.text}")
        try:
            response = res.json()
            raise Exception(f"Billing service returned bad status code: {res.status_code}", f"body:", response)
        except JSONDecodeError:
            raise Exception(f"Billing service returned bad status code: {res.status_code}", f"body:", res.text)


class BillingManager:
    license: Optional[License]
    user: Optional[User]

    def __init__(self, license, user: Optional[User] = None):
        self.license = license or get_cached_instance_license()
        self.user = user

    def get_billing(
        self,
        organization: Optional[Organization],
        query_params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        if not organization or not self.license or not self.license.is_v2_license:
            return self._get_default_billing_response(organization)

        # Get billing info from billing service
        billing_service_response = self._get_billing(organization, query_params)

        if not billing_service_response.get("customer"):
            return self._get_default_billing_response(organization)

        # Ensure the license and org are updated with the latest info
        if billing_service_response.get("license"):
            self.update_license_details(billing_service_response)

        if organization and billing_service_response:
            self.update_org_details(organization, billing_service_response)

        response: dict[str, Any] = {"available_product_features": []}

        response["license"] = {"plan": self.license.plan}

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

        return response

    def update_billing(self, organization: Organization, data: dict[str, Any]) -> None:
        res = requests.patch(
            f"{BILLING_SERVICE_URL}/api/billing/",
            headers=self.get_auth_headers(organization),
            json=data,
        )

        handle_billing_service_error(res)

    def update_available_product_features(self, organization: Organization) -> list[dict[str, Any]]:
        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/billing/available_product_features",
            headers=self.get_auth_headers(organization),
        )

        handle_billing_service_error(res)

        available_product_features_json = res.json()
        available_product_features = available_product_features_json.get("available_product_features", [])
        organization.available_product_features = available_product_features
        organization.save()

        return available_product_features

    def update_billing_organization_users(self, organization: Organization) -> None:
        try:
            distinct_ids = list(organization.members.values_list("distinct_id", flat=True))  # type: ignore

            first_owner_membership = (
                OrganizationMembership.objects.filter(organization=organization, level=15)
                .order_by("-joined_at")
                .first()
            )
            if not first_owner_membership:
                capture_exception(
                    Exception(f"No owner membership found for organization"),
                    {"organization_id": organization.id},
                )
                return
            first_owner = first_owner_membership.user

            admin_emails = list(
                organization.members.filter(
                    organization_membership__level__gte=OrganizationMembership.Level.ADMIN
                ).values_list("email", flat=True)
            )

            org_users = list(
                organization.members.values(  # type: ignore
                    "email",
                    "distinct_id",
                    "organization_membership__level",
                )
                .order_by("email")  # Deterministic order for tests
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
            capture_exception(e, {"organization_id": organization.id})

    def deactivate_products(self, organization: Organization, products: str) -> None:
        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/billing/deactivate?products={products}",
            headers=self.get_auth_headers(organization),
        )

        handle_billing_service_error(res)

    def _get_default_billing_response(self, organization: Optional[Organization]) -> dict[str, Any]:
        products = self.get_default_products(organization)
        response = {
            "available_product_features": [],
            "products": products["products"],
        }

        return response

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

    def _get_billing(self, organization: Organization, query_params: Optional[dict[str, Any]] = None) -> BillingStatus:
        """
        Retrieves billing info and updates local models if necessary
        """
        if not self.license:  # mypy
            raise Exception("No license found")

        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/billing",
            headers=self.get_auth_headers(organization),
            params=query_params,
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
                exceptions=usage_summary.get("exceptions", {}),
                recordings=usage_summary["recordings"],
                rows_synced=usage_summary.get("rows_synced", {}),
                feature_flag_requests=usage_summary.get("feature_flag_requests", {}),
                api_queries_read_bytes=usage_summary.get("api_queries_read_bytes", {}),
                period=[
                    data["billing_period"]["current_period_start"],
                    data["billing_period"]["current_period_end"],
                ],
            )

            if set_org_usage_summary(organization, new_usage=usage_info):
                org_modified = True
                update_org_billing_quotas(organization)

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
        billing_service_token = build_billing_token(self.license, organization, self.user)
        return {"Authorization": f"Bearer {billing_service_token}"}

    def get_invoices(self, organization: Organization, status: Optional[str]):
        res = requests.get(
            # TODO(@zach): update this to /api/invoices
            f"{BILLING_SERVICE_URL}/api/billing/get_invoices",
            params={"status": status},
            headers=self.get_auth_headers(organization),
        )

        handle_billing_service_error(res)

        data = res.json()

        return data

    def credits_overview(self, organization: Organization):
        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/credits/overview",
            headers=self.get_auth_headers(organization),
        )

        handle_billing_service_error(res)

        return res.json()

    def purchase_credits(self, organization: Organization, data: dict[str, Any]):
        res = requests.post(
            f"{BILLING_SERVICE_URL}/api/credits/purchase",
            headers=self.get_auth_headers(organization),
            json=data,
        )

        handle_billing_service_error(res)

        return res.json()

    def activate_trial(self, organization: Organization, data: dict[str, Any]):
        res = requests.post(
            f"{BILLING_SERVICE_URL}/api/trials/activate",
            headers=self.get_auth_headers(organization),
            json=data,
        )

        handle_billing_service_error(res)

        self.update_available_product_features(organization)

        return res.json()

    def cancel_trial(self, organization: Organization, data: dict[str, Any]):
        res = requests.post(
            f"{BILLING_SERVICE_URL}/api/trials/cancel",
            headers=self.get_auth_headers(organization),
            json=data,
        )

        handle_billing_service_error(res)

        self.update_available_product_features(organization)

    def authorize(self, organization: Organization):
        res = requests.post(
            f"{BILLING_SERVICE_URL}/api/activate/authorize",
            headers=self.get_auth_headers(organization),
        )

        handle_billing_service_error(res)

        return res.json()

    def authorize_status(self, organization: Organization, data: dict[str, Any]):
        res = requests.post(
            f"{BILLING_SERVICE_URL}/api/activate/authorize/status",
            headers=self.get_auth_headers(organization),
            json=data,
        )

        handle_billing_service_error(res)

        return res.json()

    def apply_startup_program(self, organization: Organization, data: dict[str, Any]) -> dict[str, Any]:
        res = requests.post(
            f"{BILLING_SERVICE_URL}/api/startups/apply",
            json=data,
            headers=self.get_auth_headers(organization),
        )

        handle_billing_service_error(res)
        return res.json()

    def get_usage_data(self, organization: Organization, params: dict[str, Any]) -> dict[str, Any]:
        """
        Get usage data from the billing service.
        """
        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/v2/usage/",
            headers=self.get_auth_headers(organization),
            params=params,
        )

        handle_billing_service_error(res)

        return res.json()

    def get_spend_data(self, organization: Organization, params: dict[str, Any]) -> dict[str, Any]:
        """
        Get spend data from the billing service.
        """
        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/v2/spend/",
            headers=self.get_auth_headers(organization),
            params=params,
        )

        handle_billing_service_error(res)

        return res.json()
