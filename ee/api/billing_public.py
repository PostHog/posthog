"""The public billing API: /api/organizations/{organization_id}/billing/.

Each action reads one resource from billing's /api/v2/billing/ routes with the access token
PostHog mints for the caller (ee.billing.access_token) and reshapes billing's payload into the
public contract: bare objects, ISO 8601 timestamps, the public field names. PostHog decides what
the caller may read (ee.billing.grants); billing checks the token and returns the data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional

from django.conf import settings

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.cloud_utils import get_cached_instance_license
from posthog.models import Organization, OrganizationIntegration, User
from posthog.permissions import OrganizationMemberPermissions
from posthog.rate_limit import BillingReadBurstRateThrottle, BillingReadSustainedRateThrottle
from posthog.utils import get_trusted_client_ip

from ee.billing.billing_manager import BillingManager
from ee.billing.grants import EffectiveBillingGrants, effective_billing_grants

BILLING_ACCESS_DENIED = "You do not have access to Billing for this organization."
PUBLIC_BILLING_PROVIDER = {"posthog": "stripe", "vercel": "vercel"}


def _iso(timestamp: Optional[int]) -> Optional[str]:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat().replace("+00:00", "Z")


def _billing_period(period: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not period:
        return None
    return {
        "current_period_start": _iso(period.get("current_period_start")),
        "current_period_end": _iso(period.get("current_period_end")),
        "interval": period.get("interval"),
    }


# Serializers describe the public shapes for the generated schema. The actions build plain dicts.


class BillingPeriodSerializer(serializers.Serializer):
    current_period_start = serializers.DateTimeField()
    current_period_end = serializers.DateTimeField()
    interval = serializers.ChoiceField(choices=["month", "year"])


class TrialSerializer(serializers.Serializer):
    type = serializers.CharField()
    status = serializers.CharField()
    target = serializers.CharField()
    expires_at = serializers.DateTimeField(allow_null=True)


class LicenseSerializer(serializers.Serializer):
    plan = serializers.CharField()


class BillingSubscriptionSerializer(serializers.Serializer):
    customer_id = serializers.CharField(allow_null=True)
    has_active_subscription = serializers.BooleanField()
    subscription_level = serializers.CharField(allow_null=True)
    billing_plan = serializers.CharField(allow_null=True)
    billing_provider = serializers.ChoiceField(choices=["stripe", "vercel"], allow_null=True)
    deactivated = serializers.BooleanField()
    is_annual_plan_customer = serializers.BooleanField()
    billing_period = BillingPeriodSerializer(allow_null=True)
    trial = TrialSerializer(allow_null=True)
    free_trial_until = serializers.DateTimeField(allow_null=True)
    discount_percent = serializers.IntegerField(allow_null=True)
    discount_amount_usd = serializers.CharField(allow_null=True)
    amount_off_expires_at = serializers.DateTimeField(allow_null=True)
    startup_program_label = serializers.CharField(allow_null=True)
    startup_program_label_previous = serializers.CharField(allow_null=True)
    billing_portal_url = serializers.URLField()
    invoices_url = serializers.URLField(required=False)
    license = LicenseSerializer()


class ProductFeatureSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    unit = serializers.CharField(allow_null=True, required=False)
    limit = serializers.IntegerField(allow_null=True, required=False)
    note = serializers.CharField(allow_null=True, required=False)
    is_plan_default = serializers.BooleanField(required=False)
    entitlement_only = serializers.BooleanField(allow_null=True, required=False)
    category = serializers.CharField(allow_null=True, required=False)


class BillingFeaturesSerializer(serializers.Serializer):
    available_product_features = ProductFeatureSerializer(many=True)


class PriceTierSerializer(serializers.Serializer):
    flat_amount_usd = serializers.CharField()
    unit_amount_usd = serializers.CharField()
    up_to = serializers.IntegerField(allow_null=True)


class ProductBaseFeatureSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    images = serializers.JSONField(allow_null=True, required=False)
    icon_key = serializers.CharField(allow_null=True, required=False)
    type = serializers.CharField(allow_null=True, required=False)
    category = serializers.CharField(allow_null=True, required=False)


class ProductTrialConfigSerializer(serializers.Serializer):
    length = serializers.IntegerField()


class ProductPlanSerializer(serializers.Serializer):
    product_key = serializers.CharField()
    plan_key = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    image_url = serializers.CharField(allow_null=True)
    docs_url = serializers.CharField(allow_null=True)
    note = serializers.CharField(allow_null=True)
    unit = serializers.CharField(allow_null=True)
    flat_rate = serializers.BooleanField()
    tiers = PriceTierSerializer(many=True, allow_null=True)
    free_allocation = serializers.IntegerField(allow_null=True)
    features = ProductFeatureSerializer(many=True)
    included_if = serializers.CharField(allow_null=True)
    contact_support = serializers.BooleanField(allow_null=True)
    unit_amount_usd = serializers.CharField(allow_null=True)
    current_plan = serializers.BooleanField()
    initial_billing_limit = serializers.IntegerField(allow_null=True, required=False)


class CatalogEntrySerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["product", "addon"])
    key = serializers.CharField()
    usage_key = serializers.CharField(allow_null=True)
    name = serializers.CharField()
    headline = serializers.CharField(allow_null=True)
    description = serializers.CharField(allow_blank=True)
    price_description = serializers.CharField(allow_null=True)
    icon_key = serializers.CharField(allow_null=True)
    image_url = serializers.CharField(allow_null=True)
    screenshot_url = serializers.CharField(allow_null=True)
    docs_url = serializers.CharField(allow_null=True)
    subscribed = serializers.BooleanField(allow_null=True)
    inclusion_only = serializers.BooleanField()
    contact_support = serializers.BooleanField(allow_null=True)
    legacy_product = serializers.BooleanField(allow_null=True)
    free_allocation = serializers.IntegerField(allow_null=True)
    usage_limit = serializers.IntegerField(allow_null=True)
    unit = serializers.CharField(allow_null=True)
    display_unit = serializers.CharField(allow_null=True)
    display_decimals = serializers.IntegerField(allow_null=True)
    display_divisor = serializers.FloatField(allow_null=True)
    tiered = serializers.BooleanField()
    unit_amount_usd = serializers.CharField(allow_null=True)
    tiers = PriceTierSerializer(many=True, allow_null=True)
    plans = ProductPlanSerializer(many=True, required=False)
    features = ProductBaseFeatureSerializer(many=True)
    trial = ProductTrialConfigSerializer(allow_null=True)


class BillingAddonSerializer(CatalogEntrySerializer):
    included_with_main_product = serializers.BooleanField()
    included_if = serializers.CharField(allow_null=True)
    default_unit_amount_usd = serializers.CharField(allow_null=True)


class BillingProductSerializer(CatalogEntrySerializer):
    addons = BillingAddonSerializer(many=True)


class BillingProductsSerializer(serializers.Serializer):
    results = BillingProductSerializer(many=True)


class UsageKeySummarySerializer(serializers.Serializer):
    usage_key = serializers.CharField()
    usage = serializers.IntegerField(allow_null=True)
    limit = serializers.IntegerField(allow_null=True)
    todays_usage = serializers.IntegerField(allow_null=True, required=False)
    quota_limited_until = serializers.DateTimeField(allow_null=True)
    quota_limiting_suspended_until = serializers.DateTimeField(allow_null=True)


class TierUsageSerializer(serializers.Serializer):
    up_to = serializers.IntegerField(allow_null=True)
    current_usage = serializers.IntegerField()


class UsageItemSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["product", "addon"])
    key = serializers.CharField()
    usage_key = serializers.CharField(allow_null=True)
    current_usage = serializers.IntegerField()
    usage_limit = serializers.IntegerField(allow_null=True)
    has_exceeded_limit = serializers.BooleanField()
    usage_ratio = serializers.FloatField()
    tier_usage = TierUsageSerializer(many=True, allow_null=True)


class ProductUsageSerializer(UsageItemSerializer):
    addons = UsageItemSerializer(many=True)


class BillingUsageSummarySerializer(serializers.Serializer):
    billing_period = BillingPeriodSerializer(allow_null=True)
    usage_reported_through = serializers.DateField(allow_null=True)
    usage_summary = UsageKeySummarySerializer(many=True)
    products = ProductUsageSerializer(many=True)


INCLUDE_PLANS = OpenApiParameter(
    "include_plans",
    bool,
    OpenApiParameter.QUERY,
    description="Add the `plans` list to each product and add-on. Most of the payload.",
    default=False,
)


class OrganizationBillingViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Read billing state for an organization: subscription, products, features and usage."""

    scope_object = "billing"
    scope_object_read_actions = ["subscription", "features", "products", "product", "usage"]
    scope_object_write_actions: list[str] = []
    permission_classes = [permissions.IsAuthenticated, OrganizationMemberPermissions]
    throttle_classes = [BillingReadBurstRateThrottle, BillingReadSustainedRateThrottle]
    # Opt into the generated schema. The MCP scaffolding and generated clients read it from there.
    force_include_in_api_docs = True

    def dangerously_get_queryset(self):
        """Nothing here is a model. The browsable API still asks for a queryset to build its filter
        form, and the routing mixin would filter a real one by organization. An empty queryset
        satisfies both and serves nothing."""
        return Organization.objects.none()

    def _manager(self) -> BillingManager:
        license = get_cached_instance_license()
        user = self.request.user if isinstance(self.request.user, User) and self.request.user.distinct_id else None
        return BillingManager(license, user, ip_address=get_trusted_client_ip(self.request))

    def _grants(self, request: Request, organization: Organization) -> EffectiveBillingGrants:
        user = request.user if isinstance(request.user, User) else None
        grants = effective_billing_grants(
            organization=organization, user=user, authenticator=getattr(request, "successful_authenticator", None)
        )
        if not grants.grants_anything:
            raise PermissionDenied(BILLING_ACCESS_DENIED)
        return grants

    @staticmethod
    def _include_plans(request: Request) -> bool:
        return str(request.query_params.get("include_plans", "")).lower() in {"1", "true", "yes", "on"}

    @extend_schema(
        operation_id="billing_subscription_retrieve",
        summary="Get the organization's subscription",
        responses={200: OpenApiResponse(response=BillingSubscriptionSerializer)},
    )
    @action(methods=["GET"], detail=False, url_path="subscription")
    def subscription(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        organization = self.organization
        grants = self._grants(request, organization)
        data = self._manager().get_public_subscription(organization, grants)
        license = get_cached_instance_license()
        trial = data.get("trial")
        body: dict[str, Any] = {
            "customer_id": data.get("provider_customer_id"),
            "has_active_subscription": data.get("has_active_subscription", False),
            "subscription_level": data.get("subscription_level"),
            "billing_plan": data.get("billing_plan"),
            "billing_provider": PUBLIC_BILLING_PROVIDER.get(data.get("billing_provider") or "", None),
            "deactivated": data.get("deactivated", False),
            "is_annual_plan_customer": data.get("is_annual_plan_customer", False),
            "billing_period": _billing_period(data.get("billing_period")),
            "trial": (
                {
                    "type": trial.get("type"),
                    "status": trial.get("status"),
                    "target": trial.get("target"),
                    "expires_at": _iso(trial.get("expires_at")),
                }
                if trial
                else None
            ),
            "free_trial_until": _iso((data.get("free_trial") or {}).get("expires_at")),
            "discount_percent": data.get("discount_percent"),
            "discount_amount_usd": data.get("discount_amount_usd"),
            "amount_off_expires_at": _iso(data.get("amount_off_expires_at")),
            "startup_program_label": data.get("startup_program_label"),
            "startup_program_label_previous": data.get("startup_program_label_previous"),
            "billing_portal_url": f"{settings.SITE_URL}/api/billing/portal",
            "license": {"plan": license.plan if license else None},
        }
        vercel_integration = OrganizationIntegration.objects.filter(
            organization=organization, kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL
        ).first()
        if vercel_integration and vercel_integration.integration_id:
            account_url = vercel_integration.config.get("account", {}).get("url", "")
            if account_url:
                body["invoices_url"] = f"{account_url}/invoices"
        return Response(body, status=status.HTTP_200_OK)

    @extend_schema(
        operation_id="billing_features_retrieve",
        summary="Get the features the organization's plans include",
        responses={200: OpenApiResponse(response=BillingFeaturesSerializer)},
    )
    @action(methods=["GET"], detail=False, url_path="features")
    def features(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        organization = self.organization
        grants = self._grants(request, organization)
        data = self._manager().get_public_features(organization, grants)
        return Response({"available_product_features": data.get("available_product_features", [])})

    @extend_schema(
        operation_id="billing_products_list",
        summary="List the organization's products",
        parameters=[INCLUDE_PLANS],
        responses={200: OpenApiResponse(response=BillingProductsSerializer)},
    )
    @action(methods=["GET"], detail=False, url_path="products")
    def products(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        organization = self.organization
        grants = self._grants(request, organization)
        data = self._manager().get_public_products(organization, grants, include_plans=self._include_plans(request))
        return Response({"results": data.get("products", [])})

    @extend_schema(
        operation_id="billing_products_retrieve",
        summary="Get one product",
        parameters=[INCLUDE_PLANS],
        responses={200: OpenApiResponse(response=BillingProductSerializer)},
    )
    @action(methods=["GET"], detail=False, url_path=r"products/(?P<product_key>[^/.]+)")
    def product(self, request: Request, *args: Any, product_key: str = "", **kwargs: Any) -> Response:
        organization = self.organization
        grants = self._grants(request, organization)
        data = self._manager().get_public_products(
            organization, grants, include_plans=self._include_plans(request), product_key=product_key
        )
        return Response(data.get("product"))

    @extend_schema(
        operation_id="billing_usage_summary_retrieve",
        summary="Get usage so far this billing period",
        responses={200: OpenApiResponse(response=BillingUsageSummarySerializer)},
    )
    @action(methods=["GET"], detail=False, url_path="usage")
    def usage(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        organization = self.organization
        grants = self._grants(request, organization)
        data = self._manager().get_public_usage(organization, grants)
        organization_usage = organization.usage or {}
        usage_summary = []
        for entry in data.get("usage_summary", []):
            own = organization_usage.get(entry["usage_key"])
            own = own if isinstance(own, dict) else {}
            usage_summary.append(
                {
                    **entry,
                    "todays_usage": own.get("todays_usage"),
                    "quota_limited_until": _iso(own.get("quota_limited_until")),
                    "quota_limiting_suspended_until": _iso(own.get("quota_limiting_suspended_until")),
                }
            )
        return Response(
            {
                "billing_period": _billing_period(data.get("billing_period")),
                "usage_reported_through": data.get("usage_reported_through"),
                "usage_summary": usage_summary,
                "products": data.get("products", []),
            }
        )
