import calendar
from datetime import datetime, time, timedelta
from typing import Any, Dict, Optional, Tuple

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
from posthog.models import Organization
from posthog.models.event.util import get_event_count_for_team_and_period
from posthog.models.session_recording_event.util import get_recording_count_for_team_and_period
from posthog.models.team.team import Team

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

        for team in teams:
            (start_period, end_period) = get_this_month_date_range()
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


def handle_billing_service_error(res: requests.Response, valid_codes=(200, 404)) -> None:
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
        org = self._get_org()

        # If on Cloud and we have the property billing - return 404 as we always use legacy billing it it exists
        if hasattr(org, "billing"):
            if org.billing.stripe_subscription_id:  # type: ignore
                raise NotFound("Billing V1 is active for this organization")

        billing_service_response: Dict[str, Any] = {}
        response: Dict[str, Any] = {}

        # Load Billing info if we have a V2 license
        if org and license and license.is_v2_license:
            response["license"] = {"plan": license.plan}
            billing_service_response = self._get_billing(license, org)

        # If there isn't a valid v2 subscription then we only return sucessfully if BILLING_V2_ENABLED
        if (
            not billing_service_response.get("customer", {}).get("has_active_subscription")
            and not settings.BILLING_V2_ENABLED
        ):
            distinct_id = None if self.request.user.is_anonymous else self.request.user.distinct_id
            if not (distinct_id and posthoganalytics.get_feature_flag("billing-v2-enabled", distinct_id)):
                raise NotFound("Billing V2 is not enabled for this organization")

        # Sync the License and Org if we have a valid response
        if license and billing_service_response.get("license"):
            self._update_license_details(license, billing_service_response["license"])

        if org and billing_service_response.get("customer"):
            self._update_org_details(org, billing_service_response["customer"])
            response.update(billing_service_response["customer"])

        # If we don't have products then get the default ones with our local usage calculation
        if not response.get("products"):
            products = self._get_products()
            response["products"] = products["standard"]
            response["products_enterprise"] = products["enterprise"]

            calculated_usage = get_cached_current_usage(org) if org else None

            if calculated_usage is not None:
                for product in response["products"] + response["products_enterprise"]:
                    if product["type"] in calculated_usage:
                        product["current_usage"] = calculated_usage[product["type"]]
                    else:
                        product["current_usage"] = 0

        # Either way calculate the percentage_used for each product
        for product in response["products"]:
            usage_limit = product.get("usage_limit", product.get("free_allocation"))
            product["percentage_usage"] = product["current_usage"] / usage_limit if usage_limit else 0

        return Response(response)

    @action(methods=["PATCH"], detail=False, url_path="/")
    def patch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        license = License.objects.first_valid()
        if not license:
            raise Exception("There is no license configured for this instance yet.")
        org = self._get_org_required()

        billing_service_token = build_billing_token(license, org)

        res = requests.patch(
            f"{BILLING_SERVICE_URL}/api/billing/",
            headers={"Authorization": f"Bearer {billing_service_token}"},
            json={"custom_limits_usd": request.data.get("custom_limits_usd")},
        )

        handle_billing_service_error(res)

        return self.list(request, *args, **kwargs)

    @action(methods=["GET"], detail=False)
    def activation(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = License.objects.first_valid()
        organization = self._get_org_required()

        redirect_uri = f"{settings.SITE_URL or request.headers.get('Host')}/organization/billing"
        url = f"{BILLING_SERVICE_URL}/activation?redirect_uri={redirect_uri}&organization_name={organization.name}&plan={request.GET.get('plan', 'standard')}"

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

    def _get_products(self):
        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/products",
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

        if data["available_features"] != organization.available_features:
            organization.available_features = data["available_features"]
            org_modified = True

        if data.get("deactivated"):
            # TODO: Mark the organization as deactivated
            pass

        if org_modified:
            organization.save()

        return organization
