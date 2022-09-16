from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from django.http import HttpRequest
from rest_framework import serializers, viewsets, mixins
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.response import Response
from rest_framework.exceptions import NotAuthenticated
import jwt
from ee.models.license import License
import requests

from posthog.auth import PersonalAPIKeyAuthentication
from posthog.models.organization import Organization

mock_billing_info = {
    "stripe_customer_id": "cus_12345",
    "should_setup_billing": True,
    "is_billing_active": False,
    "plan": {
        "key": "standard",
        "name": "PostHog Cloud",
        "custom_setup_billing_message": "",
        "event_allowance": None,
        "image_url": "https://posthog-static-files.s3.us-east-2.amazonaws.com/Product-Assets/billing/plan-growth.svg",
        "self_serve": True,
        "is_metered_billing": True,
        "price_string": "$0.000225/event per month - First 1,000,000 events every month for free, after subscription - Discount after 10M events",
    },
    "billing_period_ends": None,
    "event_allocation": 1000000,
    "current_usage": 276,
    "subscription_url": "/billing/setup",
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
        org: Optional[Organization] = None if self.request.user.is_anonymous else self.request.user.organization
        # TODO: Ensure user is allowed to see billing info

        license = License.objects.first_valid()

        # if license:
        #     # TODO: Get this from real billing service and not mock
        #     billing_service_token = self._build_token(org)

        #     # res = requests.get(
        #     #     f"https://billing.posthog.com/api/billing/{org.id}",
        #     #     headers={"Authorization": f"bearer {billing_service_token}"},
        #     # )
        #     return Response(mock_billing_info)

        return Response(mock_billing_info)

    def update(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Response:
        return Response(mock_billing_info)

    def _build_token(self, org):
        license = License.objects.first_valid()

        if not org or not license:
            raise NotAuthenticated()

        encoded_jwt = jwt.encode(
            {"exp": datetime.now(tz=timezone.utc) + timedelta(minutes=15)},
            license.key,
            algorithm="HS256",
        )

        return encoded_jwt
