from datetime import datetime, timedelta, timezone
from http.client import FORBIDDEN
from typing import Any, Optional

import jwt
import requests
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from rest_framework import mixins, serializers, viewsets, status
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotAuthenticated, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.request import Request

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


class BillingViewset(mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = BillingSerializer

    authentication_classes = [
        PersonalAPIKeyAuthentication,
        SessionAuthentication,
        BasicAuthentication,
    ]

    def list(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Response:
        license = License.objects.first_valid()
        org = self._get_org()

        if not license:
            return Response(UNLICENSED_BILLING_RESPONSE)

        billing_service_token = self._build_token(license, org)

        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/billing",
            headers={"Authorization": f"Bearer {billing_service_token}"},
        )

        if res.status_code == 404:
            return Response(UNLICENSED_BILLING_RESPONSE)

        # TODO: Validate that "license" part of response is the same as local and update if not

        return Response(res.json()["customer"])

    @action(methods=["GET"], detail=False)
    def activation(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        license = License.objects.first_valid()
        organization = self._get_org()

        redirect_uri = f"{settings.SITE_URL or request.headers.get('Host')}/organization/billing"
        url = f"{BILLING_SERVICE_URL}/activation?redirect_uri={redirect_uri}&organization_name={organization.name}"

        if license:
            billing_service_token = self._build_token(license, organization)
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
            headers={"Authorization": f"Bearer {self._build_token(license, organization)}"},
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

    def update(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Response:
        # TODO
        return Response(UNLICENSED_BILLING_RESPONSE)

    def _get_org(self) -> Organization:
        org = None if self.request.user.is_anonymous else self.request.user.organization

        if not org:
            raise Exception("You cannot setup billing without an organization configured.")

        return org

    def _build_token(self, license: License, org: Organization):
        if not org or not license:
            raise NotAuthenticated()

        license_id = license.key.split("::")[0]
        license_secret = license.key.split("::")[1]

        print(license_id, license_secret, BILLING_SERVICE_JWT_AUD)

        encoded_jwt = jwt.encode(
            {
                "exp": datetime.now(tz=timezone.utc) + timedelta(minutes=15),
                "id": license_id,
                "organization_id": str(org.id),
                "aud": "posthog:license-key",
            },
            license_secret,
            algorithm="HS256",
        )

        return encoded_jwt
