from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import requests
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from rest_framework import serializers, status, viewsets
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotAuthenticated, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from ee.models import License
from ee.settings import BILLING_SERVICE_URL
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.models import Organization

UNLICENSED_BILLING_RESPONSE: Any = {"subscription_url": None, "products": None, "custom_limits": {}}
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

        if license:
            billing_service_token = build_billing_token(license, str(org.id))

            res = requests.get(
                f"{BILLING_SERVICE_URL}/api/billing",
                headers={"Authorization": f"Bearer {billing_service_token}"},
            )

            if res.status_code == 200 and res.json().get("customer"):
                return Response(res.json()["customer"])

            # For all unhandled statuses we raise an exception
            if res.status_code not in (200, 404):
                raise Exception(f"Billing service returned bad status code: {res.status_code}")

        # The default response includes products but no subscription

        products = self._get_products()

        return Response({"subscription_url": None, "products": products, "custom_limits": {}})

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
            # Successfull license - let's save it
            data = res.json()
            license.valid_until = data["license"]["valid_until"]
            license.plan = data["license"]["type"]
            license.max_users = 0
            license.save()
            return Response({"success": True})

        raise ValidationError(
            {
                "license": f"License could not be activated. Please contact support. (BillingService status {res.status_code}",
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
