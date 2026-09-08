"""The organization billing API: /api/organizations/{organization_id}/billing/.

Each action reads one resource from billing's /api/v2/billing/ routes with the access token
PostHog mints for the caller (ee.billing.access_token) and reshapes billing's payload into the
organization API contract: bare objects, ISO 8601 timestamps, its own field names. PostHog decides what
the caller may read (ee.billing.grants); billing checks the token and returns the data.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Optional

from django.conf import settings
from django.db import models
from django.http import StreamingHttpResponse

import requests
from asgiref.sync import sync_to_async
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.streaming import streaming_response
from posthog.cloud_utils import get_cached_instance_license
from posthog.models import Organization, OrganizationIntegration, Team, User
from posthog.permissions import OrganizationMemberPermissions, PostHogFeatureFlagPermission
from posthog.rate_limit import BillingReadBurstRateThrottle, BillingReadSustainedRateThrottle
from posthog.utils import get_trusted_client_ip

from ee.api.billing import BillingTimeSeriesPointSerializer, BillingUsageRequestSerializer, _resolve_team_labels
from ee.billing.billing_manager import BillingManager
from ee.billing.grants import (
    ORGANIZATION_BILLING_API_FLAG,
    BillingEntitlement,
    EffectiveBillingGrants,
    effective_billing_grants,
    visible_team_ids,
)

BILLING_ACCESS_DENIED = "You do not have access to Billing for this organization."


class CatalogKind(models.TextChoices):
    """Discriminates products from add-ons wherever the two can appear together."""

    PRODUCT = "product"
    ADDON = "addon"


ORGANIZATION_BILLING_PROVIDER = {"posthog": "stripe", "vercel": "vercel"}


def _with_todays_usage(products: list[dict[str, Any]], organization_usage: dict[str, Any]) -> list[dict[str, Any]]:
    """Product and add-on rows with today's usage added to the count and the ratio, as the root
    billing read does. Billing's figures stop at the last report; PostHog holds today's."""

    def add(item: dict[str, Any]) -> dict[str, Any]:
        own = organization_usage.get(item.get("usage_key") or "")
        todays = own.get("todays_usage") if isinstance(own, dict) else None
        if not todays:
            return item
        current = int(item.get("current_usage") or 0) + int(todays)
        limit = item.get("usage_limit")
        return {**item, "current_usage": current, "usage_ratio": current / limit if limit else 0}

    return [{**add(product), "addons": [add(addon) for addon in product.get("addons", [])]} for product in products]


def fetch_invoice_document(url: str) -> requests.Response:
    """Open the provider's PDF for streaming. Its own function so tests can stub it apart from the
    calls to billing."""
    return requests.get(url, stream=True, timeout=(5, 60))


async def document_chunks(upstream: requests.Response) -> AsyncIterator[bytes]:
    """The document as it arrives from the provider, one chunk at a time.

    Under ASGI, Django reads a synchronous iterator to its end before it sends the first byte, so
    the whole document would sit in memory. An asynchronous iterator goes out chunk by chunk. Each
    read blocks on the provider, so it runs in a worker thread.
    """
    chunks = upstream.iter_content(chunk_size=64 * 1024)
    read_chunk = sync_to_async(lambda: next(chunks, None), thread_sensitive=False)
    try:
        while (chunk := await read_chunk()) is not None:
            yield chunk
    finally:
        upstream.close()


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


# Serializers describe the organization API's shapes for the generated schema. The actions build plain dicts.


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
    kind = serializers.ChoiceField(choices=CatalogKind.choices)
    key = serializers.CharField()
    usage_key = serializers.CharField(allow_null=True)
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    price_description = serializers.CharField(allow_null=True)
    icon_key = serializers.CharField(allow_null=True)
    image_url = serializers.CharField(allow_null=True)
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
    headline = serializers.CharField(allow_null=True)
    screenshot_url = serializers.CharField(allow_null=True)
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
    kind = serializers.ChoiceField(choices=CatalogKind.choices)
    key = serializers.CharField()
    usage_key = serializers.CharField(allow_null=True)
    current_usage = serializers.IntegerField()
    usage_limit = serializers.IntegerField(allow_null=True)
    has_exceeded_limit = serializers.BooleanField()
    usage_ratio = serializers.FloatField()
    tier_usage = TierUsageSerializer(many=True, allow_null=True)


class ProductUsageSerializer(UsageItemSerializer):
    addons = UsageItemSerializer(many=True)


class UsageStatusItemSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=CatalogKind.choices)
    key = serializers.CharField()
    usage_key = serializers.CharField(allow_null=True)
    usage_limit = serializers.IntegerField(allow_null=True)
    has_exceeded_limit = serializers.BooleanField()
    approaching_limit = serializers.BooleanField()
    quota_limited_until = serializers.DateTimeField(allow_null=True)
    quota_limiting_suspended_until = serializers.DateTimeField(allow_null=True)


class ProductUsageStatusSerializer(UsageStatusItemSerializer):
    addons = UsageStatusItemSerializer(many=True)


class BillingUsageStatusSerializer(serializers.Serializer):
    billing_period = BillingPeriodSerializer(allow_null=True)
    usage_reported_through = serializers.DateField(allow_null=True)
    products = ProductUsageStatusSerializer(many=True)


class BillingUsageSummarySerializer(serializers.Serializer):
    billing_period = BillingPeriodSerializer(allow_null=True)
    usage_reported_through = serializers.DateField(allow_null=True)
    usage_summary = UsageKeySummarySerializer(many=True)
    products = ProductUsageSerializer(many=True)


class TierSpendSerializer(serializers.Serializer):
    up_to = serializers.IntegerField(allow_null=True)
    current_amount_usd = serializers.CharField(allow_null=True)


class SpendItemSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=CatalogKind.choices)
    key = serializers.CharField()
    usage_key = serializers.CharField(allow_null=True)
    current_amount_usd = serializers.CharField(allow_null=True)
    current_amount_usd_before_addons = serializers.CharField(allow_null=True, required=False)
    tier_spend = TierSpendSerializer(many=True, allow_null=True)


class ProductSpendSerializer(SpendItemSerializer):
    addons = SpendItemSerializer(many=True)


class BillingSpendSummarySerializer(serializers.Serializer):
    billing_period = BillingPeriodSerializer(allow_null=True)
    usage_reported_through = serializers.DateField(allow_null=True)
    current_total_amount_usd = serializers.CharField(allow_null=True)
    current_total_amount_usd_after_discount = serializers.CharField(allow_null=True)
    products = ProductSpendSerializer(many=True)


class TierForecastSerializer(serializers.Serializer):
    up_to = serializers.IntegerField(allow_null=True)
    projected_usage = serializers.IntegerField(allow_null=True)
    projected_amount_usd = serializers.CharField(allow_null=True)


class ForecastItemSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=CatalogKind.choices)
    key = serializers.CharField()
    usage_key = serializers.CharField(allow_null=True)
    projected_usage = serializers.IntegerField(allow_null=True)
    projected_amount_usd = serializers.CharField(allow_null=True)
    projected_amount_usd_with_limit = serializers.CharField(allow_null=True, required=False)
    tier_forecast = TierForecastSerializer(many=True, allow_null=True)


class ProductForecastSerializer(ForecastItemSerializer):
    addons = ForecastItemSerializer(many=True)


class BillingForecastSerializer(serializers.Serializer):
    billing_period = BillingPeriodSerializer(allow_null=True)
    projected_total_amount_usd = serializers.CharField(allow_null=True)
    projected_total_amount_usd_with_limit = serializers.CharField(allow_null=True)
    projected_total_amount_usd_after_discount = serializers.CharField(allow_null=True)
    projected_total_amount_usd_with_limit_after_discount = serializers.CharField(allow_null=True)
    products = ProductForecastSerializer(many=True)
    computed_at = serializers.DateTimeField()


class BillingInvoiceSerializer(serializers.Serializer):
    id = serializers.CharField()
    number = serializers.CharField(allow_null=True)
    status = serializers.ChoiceField(choices=["open", "paid", "uncollectible", "void"])
    currency = serializers.CharField(allow_null=True)
    subtotal = serializers.CharField()
    total = serializers.CharField()
    amount_due = serializers.CharField()
    amount_paid = serializers.CharField()
    period_start = serializers.DateTimeField()
    period_end = serializers.DateTimeField()
    created = serializers.DateTimeField(allow_null=True)
    due_date = serializers.DateTimeField(allow_null=True)


class BillingInvoicesSerializer(serializers.Serializer):
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = BillingInvoiceSerializer(many=True)


class ProductLimitSerializer(serializers.Serializer):
    key = serializers.CharField()
    limit_usd = serializers.IntegerField(allow_null=True)
    next_period_limit_usd = serializers.IntegerField(allow_null=True)
    spend_usd = serializers.CharField(allow_null=True)
    reached = serializers.BooleanField()


class BillingLimitsSerializer(serializers.Serializer):
    results = ProductLimitSerializer(many=True)


class BillingProjectSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField(
        allow_null=True,
        help_text="The project's name, or null when the project was deleted after its usage was reported.",
    )
    deleted = serializers.BooleanField()


class BillingProjectsSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = BillingProjectSerializer(many=True)


class PaginatedBillingTimeSeriesPointListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = BillingTimeSeriesPointSerializer(many=True)


class OrganizationTimeseriesRequestSerializer(BillingUsageRequestSerializer):
    """The root series read's parameters, with its cursor paging expressed the API's way: `limit`
    and `cursor` in the request, `next` and `previous` links in the response."""

    page_size = None  # type: ignore[assignment]
    after = None  # type: ignore[assignment]
    limit = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=1000,
        help_text=(
            "Series per page, ranked by total, with a `next` link for the page after. Requires a project "
            "breakdown; ignored without one. Omit it to get every series at once."
        ),
    )
    cursor = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=512,
        help_text="The cursor from a previous page's `next` link. Opaque. Ignored without `limit`.",
    )


INCLUDE_PLANS = OpenApiParameter(
    "include_plans",
    bool,
    OpenApiParameter.QUERY,
    description="Add the `plans` list to each product and add-on. Most of the payload.",
    default=False,
)


class BillingInvoiceListParamsSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        required=False, choices=["open", "paid", "uncollectible", "void"], help_text="Only invoices in this state."
    )
    limit = serializers.IntegerField(required=False, min_value=1, max_value=100, help_text="Invoices per page.")
    cursor = serializers.CharField(required=False, help_text="The cursor from a previous page.")


@extend_schema(extensions={"x-product": "billing"})
class OrganizationBillingViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Read billing state for an organization: subscription, products, features and usage.

    The schema attributes every operation here to the billing product. Without that the route
    puts them under organizations, and the MCP tool scaffold, which matches by product, drops
    the billing tools that name them.
    """

    scope_object = "billing"
    scope_object_read_actions = [
        "subscription",
        "features",
        "products",
        "product",
        "usage",
        "usage_status",
        "spend",
        "forecast",
        "usage_timeseries",
        "spend_timeseries",
        "invoices",
        "invoice_content",
        "limits",
        "projects",
    ]
    scope_object_write_actions: list[str] = []
    # Nothing here answers until the flag is on for the caller's organization.
    posthog_feature_flag = ORGANIZATION_BILLING_API_FLAG
    permission_classes = [permissions.IsAuthenticated, OrganizationMemberPermissions, PostHogFeatureFlagPermission]
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

    @staticmethod
    def _covers(grants: EffectiveBillingGrants, level: BillingEntitlement) -> bool:
        return level.value in grants.entitlements

    @classmethod
    def _require(
        cls, grants: EffectiveBillingGrants, level: BillingEntitlement, *, whole_organization: bool = False
    ) -> None:
        """Refuse here what billing would refuse, so a caller below the level never costs a call."""
        if not cls._covers(grants, level):
            raise PermissionDenied(BILLING_ACCESS_DENIED)
        if whole_organization and grants.projects is not None:
            raise PermissionDenied("This resource is an organization total and needs a whole-organization credential.")

    def _timeseries(self, request: Request, kind: str) -> Response:
        organization = self.organization
        grants = self._grants(request, organization)
        self._require(grants, BillingEntitlement.USAGE_READ)
        serializer = OrganizationTimeseriesRequestSerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)
        params = {key: value for key, value in serializer.validated_data.items() if value is not None}
        # Billing pages with page_size and after; the API's names for the same thing are limit and cursor.
        if "limit" in params:
            params["page_size"] = params.pop("limit")
        if "cursor" in params:
            params["after"] = params.pop("cursor")
        requested = json.loads(params["team_ids"]) if params.get("team_ids") else None
        # Below full access a user's series cover the projects they can see, filtered here per
        # request as the usage and spend reads do today. The filter always names the projects, so
        # a project deleted since its usage was reported is never in it.
        user = request.user if isinstance(request.user, User) else None
        visible: set[int] | None = None
        if user is not None and not self._covers(grants, BillingEntitlement.FULL_ACCESS):
            visible = set(visible_team_ids(user, organization))
        scoped: list[int] | None
        if grants.projects is None and visible is None:
            # A whole-organization caller may name any project the organization has reported usage
            # for, deleted ones included, as the projects read lists them. Billing scopes the read
            # to the organization, so an id it never reported yields nothing.
            scoped = sorted(set(requested)) if requested is not None else None
        else:
            allowed = set(grants.projects) if grants.projects is not None else set()
            if visible is not None:
                allowed = visible if grants.projects is None else allowed & visible
                if not allowed:
                    raise PermissionDenied(BILLING_ACCESS_DENIED)
            scoped = sorted(allowed if requested is None else allowed.intersection(requested))
            if requested is not None and not scoped:
                raise PermissionDenied("The credential does not cover the requested projects.")
        if scoped is not None:
            params["team_ids"] = json.dumps(scoped)
        named = Team.objects.filter(organization=organization)
        if scoped is not None:
            named = named.filter(id__in=scoped)
        teams_map = dict(named.values_list("id", "name"))
        params["teams_map"] = {str(team_id): name for team_id, name in teams_map.items()}
        data = self._manager().get_organization_timeseries(organization, grants, kind, params)
        results = data.get("results", [])
        # Names the folded "all other projects" row and any project deleted since it reported, as the root read does.
        _resolve_team_labels(results, teams_map)
        return Response(
            {
                "count": data.get("total_count", len(results)),
                "next": self._cursor_url(request, data.get("next")),
                "previous": self._previous_url(request, data.get("previous")),
                "results": results,
            }
        )

    @extend_schema(
        operation_id="billing_subscription_retrieve",
        summary="Get the organization's subscription",
        responses={200: OpenApiResponse(response=BillingSubscriptionSerializer)},
    )
    @action(methods=["GET"], detail=False, url_path="subscription")
    def subscription(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        organization = self.organization
        grants = self._grants(request, organization)
        data = self._manager().get_organization_subscription(organization, grants)
        license = get_cached_instance_license()
        trial = data.get("trial")
        body: dict[str, Any] = {
            "customer_id": data.get("provider_customer_id"),
            "has_active_subscription": data.get("has_active_subscription", False),
            "subscription_level": data.get("subscription_level"),
            "billing_plan": data.get("billing_plan"),
            "billing_provider": ORGANIZATION_BILLING_PROVIDER.get(data.get("billing_provider") or "", None),
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
        data = self._manager().get_organization_features(organization, grants)
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
        data = self._manager().get_organization_products(
            organization, grants, include_plans=self._include_plans(request)
        )
        return Response({"results": data.get("products", [])})

    @extend_schema(
        operation_id="billing_products_retrieve",
        summary="Get one product",
        parameters=[
            OpenApiParameter("product_key", str, OpenApiParameter.PATH, description="The product's key."),
            INCLUDE_PLANS,
        ],
        responses={200: OpenApiResponse(response=BillingProductSerializer)},
    )
    @action(methods=["GET"], detail=False, url_path=r"products/(?P<product_key>[^/.]+)")
    def product(self, request: Request, *args: Any, product_key: str = "", **kwargs: Any) -> Response:
        organization = self.organization
        grants = self._grants(request, organization)
        data = self._manager().get_organization_products(
            organization, grants, include_plans=self._include_plans(request), product_key=product_key
        )
        return Response(data.get("product"))

    @extend_schema(
        operation_id="billing_spend_summary_retrieve",
        summary="Get spend so far this billing period",
        responses={200: OpenApiResponse(response=BillingSpendSummarySerializer)},
    )
    @action(methods=["GET"], detail=False, url_path="spend")
    def spend(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        organization = self.organization
        grants = self._grants(request, organization)
        self._require(grants, BillingEntitlement.USAGE_READ, whole_organization=True)
        data = self._manager().get_organization_spend(organization, grants)
        return Response({**data, "billing_period": _billing_period(data.get("billing_period"))})

    @extend_schema(
        operation_id="billing_forecast_retrieve",
        summary="Get the forecast for the rest of the billing period",
        responses={200: OpenApiResponse(response=BillingForecastSerializer)},
    )
    @action(methods=["GET"], detail=False, url_path="forecast")
    def forecast(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        organization = self.organization
        grants = self._grants(request, organization)
        self._require(grants, BillingEntitlement.FULL_ACCESS, whole_organization=True)
        data = self._manager().get_organization_forecast(organization, grants)
        return Response(
            {
                **data,
                "billing_period": _billing_period(data.get("billing_period")),
                "computed_at": _iso(data.get("computed_at")),
            }
        )

    @extend_schema(
        operation_id="billing_usage_timeseries_retrieve",
        summary="Usage over time",
        parameters=[OrganizationTimeseriesRequestSerializer],
        responses={200: OpenApiResponse(response=PaginatedBillingTimeSeriesPointListSerializer)},
    )
    @action(methods=["GET"], detail=False, url_path="usage/timeseries")
    def usage_timeseries(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._timeseries(request, "usage")

    @extend_schema(
        operation_id="billing_spend_timeseries_retrieve",
        summary="Spend over time",
        parameters=[OrganizationTimeseriesRequestSerializer],
        responses={200: OpenApiResponse(response=PaginatedBillingTimeSeriesPointListSerializer)},
    )
    @action(methods=["GET"], detail=False, url_path="spend/timeseries")
    def spend_timeseries(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._timeseries(request, "spend")

    def _cursor_url(self, request: Request, cursor: Optional[str]) -> Optional[str]:
        """The same request with the cursor swapped, so limit and any filter carry across pages."""
        if not cursor:
            return None
        params = request.query_params.copy()
        params["cursor"] = cursor
        return request.build_absolute_uri(f"{request.path}?{params.urlencode()}")

    def _previous_url(self, request: Request, cursor: Optional[str]) -> Optional[str]:
        """The page before this one. Billing names the first page with an empty cursor, and the
        link to it is the same request without one."""
        if cursor is None:
            return None
        if cursor == "":
            params = request.query_params.copy()
            params.pop("cursor", None)
            return request.build_absolute_uri(f"{request.path}?{params.urlencode()}")
        return self._cursor_url(request, cursor)

    @extend_schema(
        operation_id="billing_invoices_list",
        summary="List the organization's invoices",
        parameters=[BillingInvoiceListParamsSerializer],
        responses={200: OpenApiResponse(response=BillingInvoicesSerializer)},
    )
    @action(methods=["GET"], detail=False, url_path="invoices")
    def invoices(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        organization = self.organization
        grants = self._grants(request, organization)
        self._require(grants, BillingEntitlement.FULL_ACCESS, whole_organization=True)
        params = BillingInvoiceListParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        data = self._manager().get_organization_invoices(organization, grants, **params.validated_data)
        results = [
            {
                **invoice,
                "period_start": _iso(invoice.get("period_start")),
                "period_end": _iso(invoice.get("period_end")),
                "created": _iso(invoice.get("created")),
                "due_date": _iso(invoice.get("due_date")),
            }
            for invoice in data.get("results", [])
        ]
        return Response(
            {
                "next": self._cursor_url(request, data.get("next")),
                "previous": self._cursor_url(request, data.get("previous")),
                "results": results,
            }
        )

    @extend_schema(
        operation_id="billing_invoices_content_retrieve",
        parameters=[OpenApiParameter("invoice_id", str, OpenApiParameter.PATH, description="The invoice's id.")],
        summary="Download an invoice as PDF",
        responses={(200, "application/pdf"): OpenApiResponse(response=bytes)},
    )
    @action(methods=["GET"], detail=False, url_path=r"invoices/(?P<invoice_id>[^/.]+)/content")
    def invoice_content(
        self, request: Request, *args: Any, invoice_id: str = "", **kwargs: Any
    ) -> StreamingHttpResponse:
        """The invoice document, streamed from the billing provider by PostHog under the same access
        check as the list. The provider's own link never reaches the client."""
        organization = self.organization
        grants = self._grants(request, organization)
        self._require(grants, BillingEntitlement.FULL_ACCESS, whole_organization=True)
        url = self._manager().get_organization_invoice_pdf_url(organization, grants, invoice_id)
        upstream = fetch_invoice_document(url)
        if upstream.status_code != 200:
            upstream.close()
            raise NotFound(f"No document for invoice {invoice_id}.")
        return streaming_response(
            document_chunks(upstream),
            content_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{invoice_id}.pdf"'},
        )

    @extend_schema(
        operation_id="billing_project_list",
        summary="List the projects with usage",
        description=(
            "Every project the organization has reported usage for, deleted ones included, so a caller knows "
            "which ids a project breakdown or a team_ids filter can name. Below full billing access the list is "
            "the projects the caller can see."
        ),
        responses={200: OpenApiResponse(response=BillingProjectsSerializer)},
    )
    @action(methods=["GET"], detail=False, url_path="projects")
    def projects(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        organization = self.organization
        grants = self._grants(request, organization)
        self._require(grants, BillingEntitlement.USAGE_READ)
        reported = [
            int(item["id"])
            for item in self._manager().get_organization_projects(organization, grants).get("results", [])
        ]
        user = request.user if isinstance(request.user, User) else None
        if user is not None and not self._covers(grants, BillingEntitlement.FULL_ACCESS):
            # A deleted project cannot be checked against what a member can see, so it is not listed for them.
            visible = set(visible_team_ids(user, organization))
            reported = [team_id for team_id in reported if team_id in visible]
        names = dict(Team.objects.filter(organization=organization, id__in=reported).values_list("id", "name"))
        results = [
            {"id": team_id, "name": names.get(team_id), "deleted": team_id not in names} for team_id in sorted(reported)
        ]
        return Response({"count": len(results), "next": None, "previous": None, "results": results})

    @extend_schema(
        operation_id="billing_limits_retrieve",
        summary="Get the organization's spend limits",
        responses={200: OpenApiResponse(response=BillingLimitsSerializer)},
    )
    @action(methods=["GET"], detail=False, url_path="limits")
    def limits(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        organization = self.organization
        grants = self._grants(request, organization)
        self._require(grants, BillingEntitlement.FULL_ACCESS, whole_organization=True)
        return Response({"results": self._manager().get_organization_limits(organization, grants).get("results", [])})

    @extend_schema(
        operation_id="billing_usage_summary_retrieve",
        summary="Get usage so far this billing period",
        responses={200: OpenApiResponse(response=BillingUsageSummarySerializer)},
    )
    @action(methods=["GET"], detail=False, url_path="usage")
    def usage(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        organization = self.organization
        grants = self._grants(request, organization)
        self._require(grants, BillingEntitlement.USAGE_READ)
        data = self._manager().get_organization_usage(organization, grants)
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
                "products": _with_todays_usage(data.get("products", []), organization_usage),
            }
        )

    @extend_schema(
        operation_id="billing_usage_status_retrieve",
        summary="Get usage against limits, without the counts",
        responses={200: OpenApiResponse(response=BillingUsageStatusSerializer)},
    )
    @action(methods=["GET"], detail=False, url_path="usage/status")
    def usage_status(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """What any member may know about usage: per product and add-on, the limit in effect,
        whether usage is over or approaching it, and whether the resource is being limited right
        now. The counts themselves are on `usage` and need usage read access."""
        organization = self.organization
        grants = self._grants(request, organization)
        data = self._manager().get_organization_usage_status(organization, grants)
        organization_usage = organization.usage or {}

        def with_quota_state(item: dict[str, Any]) -> dict[str, Any]:
            own = organization_usage.get(item.get("usage_key") or "")
            own = own if isinstance(own, dict) else {}
            return {
                **item,
                "quota_limited_until": _iso(own.get("quota_limited_until")),
                "quota_limiting_suspended_until": _iso(own.get("quota_limiting_suspended_until")),
            }

        return Response(
            {
                "billing_period": _billing_period(data.get("billing_period")),
                "usage_reported_through": data.get("usage_reported_through"),
                "products": [
                    {**with_quota_state(product), "addons": [with_quota_state(a) for a in product.get("addons", [])]}
                    for product in data.get("products", [])
                ],
            }
        )
