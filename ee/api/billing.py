from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
import requests
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from rest_framework import mixins, serializers, viewsets
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotAuthenticated
from rest_framework.response import Response

from ee.models import License
from ee.settings import BILLING_SERVICE_URL
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.models import Organization

UNLICENSED_BILLING_RESPONSE = {
    "should_setup_billing": False,
    "is_billing_active": False,
    "billing_period_ends": None,
    "event_allocation": 10000,
    "current_usage": 1234,
    "subscription_url": "/api/billing-v2/activation",
    "current_bill_amount": None,
    "current_bill_usage": None,
    "current_bill_cycle": None,
    "should_display_current_bill": False,
    "billing_limit": None,
    "billing_limit_exceeded": None,
    "tiers": None,
}


class BillingSerializer(serializers.Serializer):
    plan = serializers.CharField(max_length=100)
    billing_limit = serializers.IntegerField()


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

        if license and org:
            billing_service_token = self._build_token(org)

            res = requests.get(
                f"{BILLING_SERVICE_URL}/api/billing/{org.id}",
                headers={"Authorization": f"bearer {billing_service_token}"},
            )
            return Response(res.json())

        # TODO: Return default unlicensed response...
        return Response(UNLICENSED_BILLING_RESPONSE)

    @action(methods=["GET"], detail=False)
    def activation(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        license = License.objects.first_valid()
        organization = self._get_org()
        redirect_uri = f"{settings.SITE_URL or request.headers.get('Host')}/organization/billing"  # Get from request

        url = f"{BILLING_SERVICE_URL}/activation?redirect_uri={redirect_uri}"

        if license and organization:
            billing_service_token = self._build_token(organization)
            url = f"{url}&token={billing_service_token}"

        return redirect(url)

    def update(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Response:
        # TODO
        return Response(UNLICENSED_BILLING_RESPONSE)

    def _get_org(self) -> Optional[Organization]:
        return None if self.request.user.is_anonymous else self.request.user.organization

    def _build_token(self, org: Organization):
        license = License.objects.first_valid()

        if not org or not license:
            raise NotAuthenticated()

        encoded_jwt = jwt.encode(
            {"exp": datetime.now(tz=timezone.utc) + timedelta(minutes=15), "organization_id": str(org.id)},
            license.key,
            algorithm="HS256",
        )

        return encoded_jwt
