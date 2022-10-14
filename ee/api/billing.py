import calendar
from datetime import datetime, time, timedelta
from typing import Any, Dict, Optional, Tuple

import jwt
import posthoganalytics
import pytz
import requests
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

BILLING_SERVICE_JWT_AUD = "posthog:license-key"


class BillingSerializer(serializers.Serializer):
    plan = serializers.CharField(max_length=100)
    billing_limit = serializers.IntegerField()


class LicenseKeySerializer(serializers.Serializer):
    license = serializers.CharField()


def build_billing_token(license: License, organization_id: str):
    if not organization_id or not license:
        raise NotAuthenticated()

    license_id = license.key.split("::")[0]
    license_secret = license.key.split("::")[1]

    encoded_jwt = jwt.encode(
        {
            "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=15),
            "id": license_id,
            "organization_id": str(organization_id),
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
    cache_key: str = f"monthly_usage_{organization.id}"
    usage: Optional[Dict[str, int]] = cache.get(cache_key)

    if usage is None:
        teams = Team.objects.filter(organization=organization).exclude(organization__for_internal_metrics=True)

        usage = {
            "EVENTS": 0,
            "RECORDINGS": 0,
        }

        for team in teams:
            (start_period, end_period) = get_this_month_date_range()
            usage["RECORDINGS"] += get_recording_count_for_team_and_period(team.id, start_period, end_period)
            usage["EVENTS"] += get_event_count_for_team_and_period(team.id, start_period, end_period)

        cache.set(
            cache_key,
            usage,
            min(
                settings.BILLING_USAGE_CACHING_TTL,
                (end_period - timezone.now()).total_seconds(),
            ),
        )

    return usage


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

        response: Dict[str, Any] = {}

        if license:
            billing_service_token = build_billing_token(license, str(org.id))

            res = requests.get(
                f"{BILLING_SERVICE_URL}/api/billing",
                headers={"Authorization": f"Bearer {billing_service_token}"},
            )

            data = res.json()

            if data.get("license"):
                self._update_license_details(license, data["license"])

            if res.status_code == 200 and data.get("customer"):
                response.update(data["customer"])

            # For all unhandled statuses we raise an exception
            if res.status_code not in (200, 404):
                raise Exception(f"Billing service returned bad status code: {res.status_code}")

        # If there isn't a valid v2 subscription then we only return sucessfully if BILLING_V2_ENABLED
        if not response.get("has_active_subscription") and not settings.BILLING_V2_ENABLED:
            distinct_id = None if self.request.user.is_anonymous else self.request.user.distinct_id
            # TODO: Change this to local evaluation
            if not (distinct_id and posthoganalytics.get_feature_flag("billing-v2-enabled", distinct_id)):
                raise NotFound("Billing V2 is not enabled for this organization")

        # The default response is used if there is no subscription
        if not response.get("products"):
            products = self._get_products()
            calculated_usage = get_cached_current_usage(org)

            for product in products:
                if product["type"] in calculated_usage:
                    product["current_usage"] = calculated_usage[product["type"]]
            response["products"] = products

        return Response(response)

    @action(methods=["PATCH"], detail=False, url_path="/")
    def patch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        license = License.objects.first_valid()
        if not license:
            raise Exception("There is no license configured for this instance yet.")
        org = self._get_org()

        billing_service_token = build_billing_token(license, str(org.id))

        res = requests.patch(
            f"{BILLING_SERVICE_URL}/api/billing/",
            headers={"Authorization": f"Bearer {billing_service_token}"},
            json={"custom_limits_usd": request.data.get("custom_limits_usd")},
        )

        if res.status_code == 200:
            res = requests.get(
                f"{BILLING_SERVICE_URL}/api/billing/",
                headers={"Authorization": f"Bearer {billing_service_token}"},
            )

            if res.status_code == 200 and res.json().get("customer"):
                return Response(res.json()["customer"])

        raise Exception(f"Billing service returned bad status code: {res.status_code}")

    @action(methods=["GET"], detail=False)
    def activation(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = License.objects.first_valid()
        organization = self._get_org()

        redirect_uri = f"{settings.SITE_URL or request.headers.get('Host')}/organization/billing"
        url = f"{BILLING_SERVICE_URL}/activation?redirect_uri={redirect_uri}&organization_name={organization.name}"

        if license:
            billing_service_token = build_billing_token(license, str(organization.id))
            url = f"{url}&token={billing_service_token}"

        return redirect(url)

    @action(methods=["PATCH"], detail=False)
    def license(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = License.objects.first_valid()

        if license:
            raise PermissionDenied(
                "A valid license key already exists. This must be removed before a new one can be added."
            )

        organization = self._get_org()
        serializer = LicenseKeySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        license = License(key=serializer.validated_data["license"])

        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/billing",
            headers={"Authorization": f"Bearer {build_billing_token(license, str(organization.id))}"},
        )

        if res.status_code == 200:
            data = res.json()
            self._update_license_details(license, data["license"])
            return Response({"success": True})

        raise ValidationError(
            {
                "license": f"License could not be activated. Please contact support. (BillingService status {res.status_code})",
            }
        )

    def _get_org(self) -> Organization:
        org = None if self.request.user.is_anonymous else self.request.user.organization

        if not org:
            raise Exception("You cannot setup billing without an organization configured.")

        return org

    def _get_products(self):
        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/products",
        )
        return res.json()["products"]

    def _update_license_details(self, license: License, data: Dict[str, Any]) -> License:
        """
        Ensure the license details are up-to-date locally
        """
        license.valid_until = data["valid_until"]
        license.plan = data["type"]
        license.save()

        return license
