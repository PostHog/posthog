from typing import Any

from django.http import HttpRequest
from rest_framework import serializers, viewsets, mixins
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.response import Response

from posthog.auth import PersonalAPIKeyAuthentication

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

        # TODO: Ensure user is allowed to see billing info
        print("ORG")
        print(not self.request.user.is_anonymous and self.request.user.organization)
        # TODO: Get this from real billing service and not mock

        return Response(mock_billing_info)

    def update(self, request: HttpRequest, *args: Any, **kwargs: Any) -> Response:
        return Response(mock_billing_info)
