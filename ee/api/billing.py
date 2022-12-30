import calendar
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

import jwt
import posthoganalytics
import pytz
import requests
import structlog
from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotAuthenticated, NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from ee.models import License
from ee.settings import BILLING_SERVICE_URL
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.cloud_utils import is_cloud
from posthog.models import Organization
from posthog.models.event.util import get_event_count_for_team_and_period
from posthog.models.organization import OrganizationUsageInfo
from posthog.models.session_recording_event.util import get_recording_count_for_team_and_period
from posthog.models.team.team import Team
from posthog.models.user import User

logger = structlog.get_logger(__name__)

BILLING_SERVICE_JWT_AUD = "posthog:license-key"


class BillingSerializer(serializers.Serializer):
    plan = serializers.CharField(max_length=100)
    billing_limit = serializers.IntegerField()


class LicenseKeySerializer(serializers.Serializer):
    license = serializers.CharField()


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


def get_auth_headers(license: License, organization: Organization):
    billing_service_token = build_billing_token(license, organization)
    return {"Authorization": f"Bearer {billing_service_token}"}


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


def get_cached_current_usage(organization: Organization) -> Dict[str, int]:
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


def handle_billing_service_error(res: requests.Response, valid_codes=(200, 404, 401)) -> None:
    if res.status_code not in valid_codes:
        logger.error(f"Billing service returned bad status code: {res.status_code}, body: {res.text}")
        raise Exception(f"Billing service returned bad status code: {res.status_code}")


class BillingManager:
    license: Optional[License]

    def __init__(self, license):
        self.license = license or License.objects.first_valid()

    def get_billing(self, organization: Optional[Organization]) -> Dict[str, Any]:
        billing_service_response: Dict[str, Any] = {}

        if organization and self.license and self.license.is_v2_license:
            billing_service_response = self._get_billing(organization)
            return self._process_billing_service_response(organization, billing_service_response)

        else:
            products = self.get_default_products(organization)
            return {
                "available_features": [],
                "products": products["products"],
                "products_enterprise": products["products_enterprise"],
            }

    def update_billing(self, organization: Organization, data: Dict[str, Any]) -> None:
        if not self.license:  # mypy
            raise Exception("No license found")

        res = requests.patch(
            f"{BILLING_SERVICE_URL}/api/billing/",
            headers=get_auth_headers(self.license, organization),
            json=data,
        )

        handle_billing_service_error(res)

    def get_default_products(self, organization: Optional[Organization]):
        response = {}
        # If we don't have products from the billing service then get the default ones with our local usage calculation
        products = self._get_products(organization)
        response["products"] = products["standard"]
        response["products_enterprise"] = products["enterprise"]

        calculated_usage = get_cached_current_usage(organization) if organization else None

        for product in response["products"] + response["products_enterprise"]:
            if calculated_usage and product["type"] in calculated_usage:
                product["current_usage"] = calculated_usage[product["type"]]
            else:
                product["current_usage"] = 0

        response["products"] = self._process_products(response["products"])

        return response

    def update_license_details(self, data: Dict[str, Any]) -> License:
        """
        Ensure the license details are up-to-date locally
        """
        if not self.license:  # mypy
            raise Exception("No license found")

        license_modified = False

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

    def _get_billing(self, organization: Organization) -> Dict[str, Any]:
        """
        Retrieves billing info and updates local models if necessary
        """
        if not self.license:  # mypy
            raise Exception("No license found")

        res = requests.get(f"{BILLING_SERVICE_URL}/api/billing", headers=get_auth_headers(self.license, organization))

        handle_billing_service_error(res)

        data = res.json()

        return data

    def _process_billing_service_response(
        self, organization: Optional[Organization], billing_service_response: Dict[str, Any]
    ):
        if not self.license:  # mypy
            raise Exception("No license found")

        response: Dict[str, Any] = {"available_features": []}

        response["license"] = {"plan": self.license.plan}

        # Sync the License and Org if we have a valid response
        if billing_service_response.get("license"):
            self.update_license_details(billing_service_response["license"])
        if organization and billing_service_response.get("customer"):
            response.update(billing_service_response["customer"])

        if billing_service_response["customer"].get("products"):
            response["products"] = self._process_products(billing_service_response["customer"]["products"])
        else:
            products = self.get_default_products(organization)
            response["products"] = products["products"]
            response["products_enterprise"] = products["products_enterprise"]

        # Before responding ensure the org is updated with the latest info
        if organization:
            self._update_org_details(organization, response)

        return response

    def _get_products(self, organization: Optional[Organization]):
        headers = {}
        params = {"plan": "standard"}

        if self.license and organization:
            headers = get_auth_headers(self.license, organization)

        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/products",
            params=params,
            headers=headers,
        )

        handle_billing_service_error(res)

        return res.json()

    def _process_products(self, products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:

        # Either way calculate the percentage_used for each product
        for product in products:
            usage_limit = product.get("usage_limit", product.get("free_allocation"))
            product["percentage_usage"] = product["current_usage"] / usage_limit if usage_limit else 0

        return products

    def _update_org_details(self, organization: Organization, data: Dict[str, Any]) -> Organization:
        """
        Ensure the relevant organization details are up-to-date locally
        """
        org_modified = False

        if data.get("customer_id") and organization.customer_id != data["customer_id"]:
            organization.customer_id = data["customer_id"]
            org_modified = True

        org_usage: Optional[Dict[str, OrganizationUsageInfo]] = None
        # when updating usage reports, we immediately return an organization_usage object
        if data.get("organization_usage"):
            org_usage = data["organization_usage"]
        else:
            org_usage = {
                "events": {
                    "usage": None,
                    "limit": None,
                },
                "recordings": {
                    "usage": None,
                    "limit": None,
                },
            }

            if data.get("has_active_subscription"):
                # If we have a subscription use the correct values from there
                for product in data["products"]:
                    if product["type"] in org_usage:
                        org_usage[product["type"]]["usage"] = product["current_usage"]
                        org_usage[product["type"]]["limit"] = product.get("usage_limit")
            else:
                # We don't have a subscription so use the calculated usage
                calculated_usage = get_cached_current_usage(organization)

                for key, value in calculated_usage.items():
                    if key in org_usage:
                        org_usage[key]["usage"] = value

                for product in data["products"]:
                    if product["type"] in org_usage:
                        org_usage[product["type"]]["limit"] = product.get("free_allocation")

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


class BillingViewset(viewsets.GenericViewSet):
    serializer_class = BillingSerializer

    authentication_classes = [
        PersonalAPIKeyAuthentication,
        SessionAuthentication,
        BasicAuthentication,
    ]

    def list(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Response:
        license = License.objects.first_valid()
        if license and not license.is_v2_license:
            raise NotFound("Billing V2 is not supported for this license type")

        org = self._get_org()

        # If on Cloud and we have the property billing - return 404 as we always use legacy billing it it exists
        if hasattr(org, "billing"):
            if org.billing.stripe_subscription_id:  # type: ignore
                raise NotFound("Billing V1 is active for this organization")

        response = BillingManager(license).get_billing(org)

        return Response(response)

    @action(methods=["PATCH"], detail=False, url_path="/")
    def patch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        distinct_id = None if self.request.user.is_anonymous else self.request.user.distinct_id
        license = License.objects.first_valid()
        if not license:
            raise Exception("There is no license configured for this instance yet.")

        org = self._get_org_required()
        if license and org:  # for mypy

            custom_limits_usd = request.data.get("custom_limits_usd")
            if custom_limits_usd:
                BillingManager(license).update_billing(org, {"custom_limits_usd": custom_limits_usd})

                if distinct_id:
                    posthoganalytics.capture(distinct_id, "billing limits updated", properties={**custom_limits_usd})
                    posthoganalytics.group_identify(
                        "organization",
                        str(org.id),
                        properties={f"billing_limits_{key}": value for key, value in custom_limits_usd.items()},
                    )

        return self.list(request, *args, **kwargs)

    @action(methods=["GET"], detail=False)
    def activation(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = License.objects.first_valid()
        organization = self._get_org_required()

        redirect_path = request.GET.get("redirect_path") or "organization/billing"
        if redirect_path.startswith("/"):
            redirect_path = redirect_path[1:]

        plan = request.GET.get("plan", "standard")

        redirect_uri = f"{settings.SITE_URL or request.headers.get('Host')}/{redirect_path}"
        url = f"{BILLING_SERVICE_URL}/activation?redirect_uri={redirect_uri}&organization_name={organization.name}&plan={plan}"

        if license:
            billing_service_token = build_billing_token(license, organization)
            url = f"{url}&token={billing_service_token}"

        return redirect(url)

    @action(methods=["PATCH"], detail=False)
    def license(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = License.objects.first_valid()

        if license:
            raise PermissionDenied(
                "A valid license key already exists. This must be removed before a new one can be added."
            )

        organization = self._get_org_required()

        serializer = LicenseKeySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        license = License(key=serializer.validated_data["license"])

        res = requests.get(f"{BILLING_SERVICE_URL}/api/billing", headers=get_auth_headers(license, organization))

        if res.status_code != 200:
            raise ValidationError(
                {
                    "license": f"License could not be activated. Please contact support. (BillingService status {res.status_code})",
                }
            )
        data = res.json()
        BillingManager(license).update_license_details(data["license"])
        return Response({"success": True})

    def _get_org(self) -> Optional[Organization]:
        org = None if self.request.user.is_anonymous else self.request.user.organization

        return org

    def _get_org_required(self) -> Organization:
        org = self._get_org()

        if not org:
            raise Exception("You cannot interact with the billing service without an organization configured.")

        return org
