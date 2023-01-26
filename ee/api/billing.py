from datetime import timedelta
from typing import Any, Dict, Optional

import posthoganalytics
import requests
import structlog
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from ee.billing.billing_utils import build_billing_token, get_cached_current_usage
from ee.models import License
from ee.settings import BILLING_SERVICE_URL
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.models import Organization
from posthog.models.organization import OrganizationUsageInfo

logger = structlog.get_logger(__name__)

BILLING_SERVICE_JWT_AUD = "posthog:license-key"


class BillingSerializer(serializers.Serializer):
    plan = serializers.CharField(max_length=100)
    billing_limit = serializers.IntegerField()


class LicenseKeySerializer(serializers.Serializer):
    license = serializers.CharField()


def handle_billing_service_error(res: requests.Response, valid_codes=(200, 404, 401)) -> None:
    if res.status_code not in valid_codes:
        logger.error(f"Billing service returned bad status code: {res.status_code}, body: {res.text}")
        raise Exception(f"Billing service returned bad status code: {res.status_code}")


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

        billing_service_response: Dict[str, Any] = {}
        response: Dict[str, Any] = {"available_features": []}

        # Load Billing info if we have a V2 license
        if org and license and license.is_v2_license:
            response["license"] = {"plan": license.plan}
            billing_service_response = self._get_billing(license, org)

        # Sync the License and Org if we have a valid response
        if license and billing_service_response.get("license"):
            self._update_license_details(license, billing_service_response["license"])

        if org and billing_service_response.get("customer"):
            response.update(billing_service_response["customer"])

        # If we don't have products then get the default ones with our local usage calculation
        if not response.get("products"):
            products = self._get_products(license, org)
            response["products"] = products["standard"]
            response["products_enterprise"] = products["enterprise"]

            calculated_usage = get_cached_current_usage(org) if org else None

            for product in response["products"] + response["products_enterprise"]:
                if calculated_usage and product["type"] in calculated_usage:
                    product["current_usage"] = calculated_usage[product["type"]]
                else:
                    product["current_usage"] = 0

        # Either way calculate the percentage_used for each product
        for product in response["products"]:
            usage_limit = product.get("usage_limit", product.get("free_allocation"))
            product["percentage_usage"] = product["current_usage"] / usage_limit if usage_limit else 0

        # Before responding ensure the org is updated with the latest info
        if org:
            self._update_org_details(org, response)

        return Response(response)

    @action(methods=["PATCH"], detail=False, url_path="/")
    def patch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        distinct_id = None if self.request.user.is_anonymous else self.request.user.distinct_id
        license = License.objects.first_valid()
        if not license:
            raise Exception("There is no license configured for this instance yet.")

        org = self._get_org_required()
        if license and org:  # for mypy
            billing_service_token = build_billing_token(license, org)

            custom_limits_usd = request.data.get("custom_limits_usd")
            if custom_limits_usd:
                res = requests.patch(
                    f"{BILLING_SERVICE_URL}/api/billing/",
                    headers={"Authorization": f"Bearer {billing_service_token}"},
                    json={"custom_limits_usd": custom_limits_usd},
                )

                handle_billing_service_error(res)

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

        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/billing",
            headers={"Authorization": f"Bearer {build_billing_token(license, organization)}"},
        )

        if res.status_code != 200:
            raise ValidationError(
                {
                    "license": f"License could not be activated. Please contact support. (BillingService status {res.status_code})",
                }
            )
        data = res.json()
        self._update_license_details(license, data["license"])
        return Response({"success": True})

    def _get_org(self) -> Optional[Organization]:
        org = None if self.request.user.is_anonymous else self.request.user.organization

        return org

    def _get_org_required(self) -> Organization:
        org = self._get_org()

        if not org:
            raise Exception("You cannot setup billing without an organization configured.")

        return org

    def _get_products(self, license: Optional[License], organization: Optional[Organization]):
        headers = {}
        params = {"plan": "standard"}

        if license and organization:
            billing_service_token = build_billing_token(license, organization)
            headers = {"Authorization": f"Bearer {billing_service_token}"}
            params = {"plan": "standard"}

        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/products",
            params=params,
            headers=headers,
        )

        handle_billing_service_error(res)

        return res.json()

    def _get_billing(self, license: License, organization: Organization) -> Dict[str, Any]:
        """
        Retrieves billing info and updates local models if necessary
        """
        billing_service_token = build_billing_token(license, organization)

        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/billing",
            headers={"Authorization": f"Bearer {billing_service_token}"},
        )

        handle_billing_service_error(res)

        data = res.json()

        return data

    def _update_license_details(self, license: License, data: Dict[str, Any]) -> License:
        """
        Ensure the license details are up-to-date locally
        """
        license_modified = False

        if not license.valid_until or license.valid_until < timezone.now() + timedelta(days=29):
            # NOTE: License validity is a legacy concept. For now we always extend the license validity by 30 days.
            license.valid_until = timezone.now() + timedelta(days=30)
            license_modified = True

        if license.plan != data["type"]:
            license.plan = data["type"]
            license_modified = True

        if license_modified:
            license.save()

        return license

    def _update_org_details(self, organization: Organization, data: Dict[str, Any]) -> Organization:
        """
        Ensure the relevant organization details are up-to-date locally
        """
        org_modified = False

        if data.get("customer_id") and organization.customer_id != data["customer_id"]:
            organization.customer_id = data["customer_id"]
            org_modified = True

        usage: Dict[str, OrganizationUsageInfo] = {
            "events": {
                "usage": None,
                "limit": None,
            },
            "recordings": {"usage": None, "limit": None},
        }

        if data.get("has_active_subscription"):
            # If we have a subscription use the correct values from there
            for product in data["products"]:
                if product["type"] in usage:
                    usage[product["type"]]["usage"] = product["current_usage"]
                    usage[product["type"]]["limit"] = product.get("usage_limit")
        else:
            # We don't have a subscription so use the calculated usage
            calculated_usage = get_cached_current_usage(organization)

            for key, value in calculated_usage.items():
                if key in usage:
                    usage[key]["usage"] = value

            for product in data["products"]:
                if product["type"] in usage:
                    usage[product["type"]]["limit"] = product.get("free_allocation")

        if usage != organization.usage:
            organization.usage = usage
            org_modified = True

        if data["available_features"] != organization.available_features:
            organization.available_features = data["available_features"]
            org_modified = True

        if org_modified:
            organization.save()

        return organization
