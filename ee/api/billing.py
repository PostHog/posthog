import json
from collections.abc import Callable, Sequence
from typing import Any, Optional
from zoneinfo import ZoneInfo

from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils import timezone

import requests
import structlog
import posthoganalytics
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_serializer
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.cloud_utils import get_cached_instance_license
from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.models import Organization, OrganizationIntegration, Team, User
from posthog.models.organization import OrganizationMembership
from posthog.permissions import (
    get_authenticator_scoped_team_ids,
    get_authenticator_scopes,
    posthog_feature_flag_enabled,
)
from posthog.user_permissions import UserPermissions
from posthog.utils import get_trusted_client_ip, relative_date_parse

from products.access_control.backend.facade.user_access_control import UserAccessControl, visible_teams_for_user

from ee.billing.billing_manager import BillingManager
from ee.billing.billing_types import USAGE_TYPE_VALUES
from ee.models import License
from ee.settings import BILLING_SERVICE_URL

logger = structlog.get_logger(__name__)

BILLING_SERVICE_JWT_AUD = "posthog:license-key"
OWNER_ONLY_BILLING_FLAG = "owner-only-billing"
MEMBER_BILLING_USAGE_SPEND_READ_ACCESS_FLAG = "member-billing-usage-spend-read-access"


def _owner_only_billing_enabled(user: User, organization: Organization) -> Optional[bool]:
    if not user.distinct_id:
        return None

    try:
        return posthog_feature_flag_enabled(
            OWNER_ONLY_BILLING_FLAG,
            str(user.distinct_id),
            organization_id=organization.id,
        )
    except Exception as e:
        capture_exception(e, {"organization_id": organization.id, "flag": OWNER_ONLY_BILLING_FLAG})
        return None


def user_has_billing_access(user: User, organization: Organization) -> bool:
    membership = OrganizationMembership.objects.filter(user=user, organization=organization).only("level").first()
    if not membership:
        return False

    if membership.level >= OrganizationMembership.Level.OWNER:
        return True

    if membership.level < OrganizationMembership.Level.ADMIN:
        return False

    # Only a confirmed disabled flag lets admins through. Unknown flag state fails closed to owners.
    return _owner_only_billing_enabled(user, organization) is False


def _member_billing_usage_spend_read_access_enabled(user: User, organization: Organization) -> bool:
    if not user.distinct_id:
        return False

    try:
        return (
            posthog_feature_flag_enabled(
                MEMBER_BILLING_USAGE_SPEND_READ_ACCESS_FLAG,
                str(user.distinct_id),
                organization_id=organization.id,
            )
            is True
        )
    except Exception as e:
        capture_exception(e, {"organization_id": organization.id, "flag": MEMBER_BILLING_USAGE_SPEND_READ_ACCESS_FLAG})
        return False


def user_has_billing_usage_spend_read_access(user: User, organization: Organization) -> bool:
    membership = OrganizationMembership.objects.filter(user=user, organization=organization).only("level").first()
    if not membership:
        return False

    if membership.level >= OrganizationMembership.Level.OWNER:
        return True

    # Only a confirmed disabled flag lets non-owners through. Unknown flag state fails closed to owners.
    if _owner_only_billing_enabled(user, organization) is not False:
        return False

    if membership.level >= OrganizationMembership.Level.ADMIN:
        return True

    if membership.level < OrganizationMembership.Level.MEMBER:
        return False

    return _member_billing_usage_spend_read_access_enabled(user, organization)


def is_token_auth_request(request: Request) -> bool:
    return get_authenticator_scopes(getattr(request, "successful_authenticator", None)) is not None


class HasBillingAccess(permissions.BasePermission):
    """
    Permission to allow users with Billing access to access Billing endpoints.
    """

    message = "You do not have access to Billing for this organization."

    def has_permission(self, request: Request, view: Any) -> bool:
        try:
            org = view._get_org_required()
        except Exception:
            return False

        if not isinstance(request.user, User):
            return False

        return user_has_billing_access(request.user, org)


class HasBillingUsageSpendReadAccess(permissions.BasePermission):
    """
    Permission for read-only billing usage/spend endpoints. The frontend additionally requires
    usage-spend-dashboards before honoring the member grant, but that flag is not an authorization
    input here or in the billing service.
    """

    message = "You do not have access to billing usage and spend data for this organization."

    def has_permission(self, request: Request, view: Any) -> bool:
        try:
            org = view._get_org_required()
        except Exception:
            return False

        if not isinstance(request.user, User):
            return False

        return user_has_billing_usage_spend_read_access(request.user, org)


class BillingSerializer(serializers.Serializer):
    plan = serializers.CharField(max_length=100)
    billing_limit = serializers.IntegerField()


@extend_schema_serializer(many=False)
class BillingOverviewResponseSerializer(serializers.Serializer):
    customer_id = serializers.CharField(required=False, allow_null=True)
    billing_plan = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    subscription_level = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    has_active_subscription = serializers.BooleanField(required=False)
    deactivated = serializers.BooleanField(required=False)
    is_annual_plan_customer = serializers.BooleanField(required=False)
    free_trial_until = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    current_total_amount_usd = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    current_total_amount_usd_after_discount = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    projected_total_amount_usd = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    projected_total_amount_usd_after_discount = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    projected_total_amount_usd_with_limit = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    projected_total_amount_usd_with_limit_after_discount = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )
    discount_amount_usd = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    discount_percent = serializers.FloatField(required=False, allow_null=True)
    amount_off_expires_at = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    startup_program_label = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    startup_program_label_previous = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    stripe_portal_url = serializers.URLField(required=False, allow_blank=True, allow_null=True)
    external_billing_provider_invoices_url = serializers.URLField(required=False, allow_blank=True, allow_null=True)
    products = serializers.ListField(
        child=serializers.DictField(child=serializers.JSONField(allow_null=True)),
        required=False,
        help_text="Subscribed and available products/addons with pricing, plan, limit, usage, and entitlement metadata.",
    )
    available_product_features = serializers.ListField(child=serializers.CharField(), required=False)
    usage_summary = serializers.JSONField(required=False)
    billing_period = serializers.JSONField(required=False, allow_null=True)
    custom_limits_usd = serializers.JSONField(required=False)
    next_period_custom_limits_usd = serializers.JSONField(required=False)
    trial = serializers.JSONField(required=False, allow_null=True)
    license = serializers.JSONField(required=False, allow_null=True)
    account_owner = serializers.JSONField(required=False, allow_null=True)
    customer_trust_scores = serializers.JSONField(required=False)
    never_drop_data = serializers.BooleanField(required=False)


class LicenseKeySerializer(serializers.Serializer):
    license = serializers.CharField()


class BillingUsageRequestSerializer(serializers.Serializer):
    """
    Serializer for the usage and spend requests to the billing service.
    Only responsible for parsing dates, passes through other params.
    """

    start_date = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    end_date = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    usage_types = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text=(
            "JSON-encoded array of usage type identifiers to filter on. Valid values: "
            + ", ".join(USAGE_TYPE_VALUES)
            + '. E.g. ["event_count_in_period","recording_count_in_period"]. Omit for all types.'
        ),
    )
    team_ids = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text=(
            "JSON-encoded array of numeric team/project IDs to filter on, "
            "for example [1,2]. Omit for all projects available to the caller. Full billing-access callers can read "
            "all organization projects; member read-only callers are limited to visible projects and any project "
            "scope on their token."
        ),
    )
    breakdowns = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text=(
            'JSON-encoded array of breakdown dimensions. Valid values are "type" and "team", '
            'for example ["type","team"]. Omit for a single aggregate series.'
        ),
    )
    interval = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def _parse_date(self, date_str: Optional[str], field_name: str) -> Optional[str]:
        """Shared date parsing logic into YYYY-MM-DD format. Handles relative dates too."""
        if not date_str:
            return None

        try:
            parsed_date = relative_date_parse(date_str, ZoneInfo("UTC"))
            return parsed_date.strftime("%Y-%m-%d")
        except Exception:
            raise serializers.ValidationError({field_name: f"Could not parse date '{date_str}'."})

    def validate_start_date(self, value: Optional[str]) -> Optional[str]:
        """Validate and normalize the start_date, handling 'all'."""
        if value == "all":
            return "2020-01-01"
        return self._parse_date(value, "start_date")

    def validate_end_date(self, value: Optional[str]) -> Optional[str]:
        """Validate and normalize the end_date."""
        return self._parse_date(value, "end_date")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("start_date") and not attrs.get("end_date"):
            attrs["end_date"] = timezone.now().date().isoformat()
        return attrs

    def validate_usage_types(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return value

        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            raise serializers.ValidationError("Value must be a JSON array of usage type identifiers.")

        if not isinstance(parsed, list) or any(not isinstance(usage_type, str) for usage_type in parsed):
            raise serializers.ValidationError("Value must be a JSON array of usage type identifiers.")

        return value

    def validate_team_ids(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return value

        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            raise serializers.ValidationError("Value must be a JSON array of numeric team IDs.")

        if not isinstance(parsed, list) or any(
            not isinstance(team_id, int) or isinstance(team_id, bool) for team_id in parsed
        ):
            raise serializers.ValidationError("Value must be a JSON array of numeric team IDs.")

        return value

    def validate_breakdowns(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return value

        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            raise serializers.ValidationError("Value must be a JSON array containing only 'type' and/or 'team'.")

        if not isinstance(parsed, list) or any(breakdown not in ("type", "team") for breakdown in parsed):
            raise serializers.ValidationError("Value must be a JSON array containing only 'type' and/or 'team'.")

        return value


class BillingTimeSeriesPointSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    label = serializers.CharField(required=False, allow_blank=True)  # type: ignore[assignment]
    data = serializers.ListField(child=serializers.FloatField(), required=False)  # type: ignore[assignment]
    dates = serializers.ListField(child=serializers.CharField(), required=False)
    breakdown_type = serializers.ChoiceField(choices=["type", "team", "multiple"], allow_null=True, required=False)
    breakdown_value = serializers.JSONField(allow_null=True, required=False)


class BillingTimeSeriesResponseSerializer(serializers.Serializer):
    status = serializers.CharField(required=False)
    type = serializers.CharField(required=False)
    customer_id = serializers.IntegerField(required=False)
    results = BillingTimeSeriesPointSerializer(many=True)
    team_id_options = serializers.ListField(child=serializers.IntegerField(), required=False)
    next = serializers.CharField(required=False, allow_blank=True)


class BillingPeriodResponseSerializer(serializers.Serializer):
    current_period_start = serializers.DateTimeField(
        allow_null=True,
        help_text="Start of the organization's current billing period, or null when billing has not synced a period.",
    )
    current_period_end = serializers.DateTimeField(
        allow_null=True,
        help_text="End of the organization's current billing period, or null when billing has not synced a period.",
    )


@extend_schema(tags=["billing"])
class BillingViewset(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = BillingSerializer
    pagination_class = None
    param_derived_from_user_current_team = "team_id"

    scope_object = "billing"
    scope_object_read_actions = ["list", "usage", "spend"]
    scope_object_write_actions: list[str] = []
    # OpenAPI skips root-router viewsets that derive their team from the current user.
    # Billing opts in so generated clients and MCP scaffolding include these read actions.
    force_include_in_api_docs = True

    def get_billing_manager(self) -> BillingManager:
        license = get_cached_instance_license()
        user = self.request.user if isinstance(self.request.user, User) and self.request.user.distinct_id else None
        return BillingManager(license, user, ip_address=get_trusted_client_ip(self.request))

    @extend_schema(responses={200: OpenApiResponse(response=BillingOverviewResponseSerializer)})
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        license = get_cached_instance_license()
        if license and not license.is_v2_license:
            raise NotFound("Billing is not supported for this license type")

        org = self._get_org()
        if is_token_auth_request(request):
            if not org or not isinstance(request.user, User) or not user_has_billing_access(request.user, org):
                raise PermissionDenied("You do not have access to Billing for this organization.")

        # If on Cloud and we have the property billing - return 404 as we always use legacy billing it it exists
        if hasattr(org, "billing"):
            if org.billing.stripe_subscription_id:  # type: ignore
                raise NotFound("Billing V1 is active for this organization")

        billing_manager = self.get_billing_manager()
        query = {}
        if "include_forecasting" in request.query_params:
            query["include_forecasting"] = request.query_params.get("include_forecasting")
        response = billing_manager.get_billing(org, query)

        vercel_integration = OrganizationIntegration.objects.filter(
            organization=org,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
        ).first()

        if vercel_integration and vercel_integration.integration_id:
            account_url = vercel_integration.config.get("account", {}).get("url", "")
            if account_url:
                response["external_billing_provider_invoices_url"] = f"{account_url}/invoices"

        return Response(response)

    @extend_schema(
        summary="Get the current organization billing period",
        responses={200: BillingPeriodResponseSerializer},
    )
    @action(
        methods=["GET"],
        detail=False,
        url_path="period",
        permission_classes=[permissions.IsAuthenticated],
        required_scopes=["llm_gateway:read"],
    )
    def period(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        billing_period = self._get_org_required().current_billing_period
        return Response(
            BillingPeriodResponseSerializer(
                {
                    "current_period_start": billing_period.start if billing_period else None,
                    "current_period_end": billing_period.end if billing_period else None,
                }
            ).data
        )

    @extend_schema(exclude=True)
    @action(
        methods=["PATCH"],
        detail=False,
        url_path="/",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess],
    )
    def patch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        distinct_id = None if self.request.user.is_anonymous else self.request.user.distinct_id
        license = get_cached_instance_license()
        if not license:
            raise Exception("There is no license configured for this instance yet.")

        org = self._get_org_required()
        if license and org:  # for mypy
            custom_limits_usd = request.data.get("custom_limits_usd")
            reset_limit_next_period = request.data.get("reset_limit_next_period")

            if custom_limits_usd or reset_limit_next_period:
                body = {}
                if custom_limits_usd:
                    body["custom_limits_usd"] = custom_limits_usd
                if reset_limit_next_period:
                    body["reset_limit_next_period"] = reset_limit_next_period

                billing_manager = self.get_billing_manager()
                billing_manager.update_billing(org, body)

                if custom_limits_usd and distinct_id:
                    posthoganalytics.capture(
                        "billing limits updated",
                        distinct_id=distinct_id,
                        properties={**custom_limits_usd},
                        groups=(
                            groups(org, self.request.user.team) if hasattr(self.request.user, "team") else groups(org)
                        ),
                    )
                    posthoganalytics.group_identify(
                        "organization",
                        str(org.id),
                        properties={f"billing_limits_{key}": value for key, value in custom_limits_usd.items()},
                    )

                if reset_limit_next_period and distinct_id:
                    posthoganalytics.capture(
                        "billing limits reset",
                        distinct_id=distinct_id,
                        properties={"reset_limit_next_period": reset_limit_next_period},
                    )
                    posthoganalytics.group_identify(
                        "organization",
                        str(org.id),
                        properties={"reset_limit_next_period": reset_limit_next_period},
                    )

        return self.list(request, *args, **kwargs)

    @action(
        methods=["POST"],
        detail=False,
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess],
    )
    def activate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        organization = self._get_org_required()
        billing_manager = self.get_billing_manager()
        res = billing_manager.activate_subscription(organization, request.data)
        return Response(res, status=status.HTTP_200_OK)

    class DeactivateSerializer(serializers.Serializer):
        products = serializers.CharField()

    @action(
        methods=["POST"],
        detail=False,
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess],
    )
    def deactivate(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        organization = self._get_org_required()

        serializer = self.DeactivateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        products = serializer.validated_data.get("products")

        try:
            billing_manager = self.get_billing_manager()
            billing_manager.deactivate_products(organization, products)
        except Exception as e:
            if len(e.args) > 2:
                detail_object = e.args[2]
                return Response(
                    {
                        "statusText": e.args[0],
                        "detail": detail_object.get("error_message", detail_object),
                        "link": detail_object.get("link", None),
                        "code": detail_object.get("code"),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            else:
                raise

        return self.list(request, *args, **kwargs)

    @action(
        methods=["POST"],
        detail=False,
        url_path="subscription/switch-plan",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess],
    )
    def subscription_switch_plan(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        organization = self._get_org_required()
        billing_manager = self.get_billing_manager()
        res = billing_manager.switch_plan(organization, request.data)
        return Response(res, status=status.HTTP_200_OK)

    @action(
        methods=["GET"],
        detail=False,
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess],
    )
    def portal(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = get_cached_instance_license()
        if not license:
            return Response(
                {"success": True},
                status=status.HTTP_200_OK,
            )

        organization = self._get_org_required()

        billing_manager = self.get_billing_manager()
        res = billing_manager._get_stripe_portal_url(organization)
        return redirect(res)

    @action(methods=["GET"], detail=False)
    def get_invoices(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = get_cached_instance_license()
        if not license:
            return Response(
                {"success": True},
                status=status.HTTP_200_OK,
            )

        organization = self._get_org_required()

        invoice_status = request.GET.get("status")

        try:
            billing_manager = self.get_billing_manager()
            res = billing_manager.get_invoices(organization, status=invoice_status)
        except Exception as e:
            if len(e.args) > 2:
                detail_object = e.args[2]
                if not isinstance(detail_object, dict):
                    raise
                return Response(
                    {
                        "statusText": e.args[0],
                        "detail": detail_object.get("error_message", detail_object),
                        "code": detail_object.get("code"),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            else:
                raise

        return Response(
            {
                "link": res.get("portal_url"),
                "count": res.get("count"),
            },
            status=status.HTTP_200_OK,
        )

    @action(methods=["GET"], detail=False, url_path="credits/overview")
    def credits_overview(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = get_cached_instance_license()
        if not license:
            return Response(
                {"success": True},
                status=status.HTTP_200_OK,
            )

        organization = self._get_org_required()

        billing_manager = self.get_billing_manager()
        res = billing_manager.credits_overview(organization)
        return Response(res, status=status.HTTP_200_OK)

    @action(
        methods=["POST"],
        detail=False,
        url_path="credits/purchase",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess],
    )
    def purchase_credits(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = get_cached_instance_license()
        if not license:
            return Response(
                {"success": True},
                status=status.HTTP_200_OK,
            )

        organization = self._get_org_required()

        billing_manager = self.get_billing_manager()
        res = billing_manager.purchase_credits(organization, request.data)
        return Response(res, status=status.HTTP_200_OK)

    @action(
        methods=["POST"],
        detail=False,
        url_path="trials/activate",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess],
    )
    def activate_trial(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        organization = self._get_org_required()
        billing_manager = self.get_billing_manager()
        res = billing_manager.activate_trial(organization, request.data)
        return Response(res, status=status.HTTP_200_OK)

    @action(
        methods=["POST"],
        detail=False,
        url_path="trials/cancel",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess],
    )
    def cancel_trial(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        organization = self._get_org_required()
        billing_manager = self.get_billing_manager()
        res = billing_manager.cancel_trial(organization, request.data)
        return Response(res, status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=False, url_path="activate/authorize")
    def authorize(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = get_cached_instance_license()
        if not license:
            return Response(
                {"success": True},
                status=status.HTTP_200_OK,
            )

        organization = self._get_org_required()
        billing_manager = self.get_billing_manager()
        res = billing_manager.authorize(organization)
        return Response(res, status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=False, url_path="activate/authorize/status")
    def authorize_status(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = get_cached_instance_license()
        if not license:
            return Response(
                {"success": True},
                status=status.HTTP_200_OK,
            )

        organization = self._get_org_required()
        billing_manager = self.get_billing_manager()
        res = billing_manager.authorize_status(organization, request.data)
        return Response(res, status=status.HTTP_200_OK)

    @action(
        methods=["PATCH"],
        detail=False,
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess],
    )
    def license(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = get_cached_instance_license()

        if license:
            raise PermissionDenied(
                "A valid license key already exists. This must be removed before a new one can be added."
            )

        organization = self._get_org_required()

        serializer = LicenseKeySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        license = License(key=serializer.validated_data["license"])
        ip_address = get_trusted_client_ip(request)
        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/billing",
            headers=BillingManager(license, ip_address=ip_address).get_auth_headers(organization),
        )

        if res.status_code != 200:
            raise ValidationError(
                {
                    "license": f"License could not be activated. Please contact support. (BillingService status {res.status_code})",
                }
            )
        data = res.json()
        BillingManager(license, ip_address=ip_address).update_license_details(data)
        return Response({"success": True})

    @action(
        methods=["POST"],
        detail=False,
        url_path="startups/apply",
        permission_classes=[permissions.IsAuthenticated],
    )
    def apply_startup_program(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        user = self.request.user
        if not isinstance(user, User):
            raise PermissionDenied("You must be logged in to apply for the startup program")

        organization_id = request.data.get("organization_id")
        if not organization_id:
            raise ValidationError({"organization_id": "This field is required."})

        organization = Organization.objects.get(id=organization_id)
        if not organization:
            raise ValidationError({"organization_id": "Organization not found."})

        if not user_has_billing_access(user, organization):
            raise PermissionDenied("You need Billing access to apply for the startup program")

        billing_manager = self.get_billing_manager()

        # Add user info to the request
        data = {
            **request.data,
            "email": user.email,
        }

        # "-" as fallback as they're required by some of the Zaps, e.g. Brilliant (merch)
        data["first_name"] = user.first_name if user.first_name else "-"
        data["last_name"] = user.last_name if user.last_name else "-"

        try:
            res = billing_manager.apply_startup_program(organization, data)
            return Response(res, status=status.HTTP_200_OK)
        except Exception as e:
            if len(e.args) > 2:
                detail_object = e.args[2]
                if not isinstance(detail_object, dict):
                    raise
                return Response(
                    {
                        "statusText": e.args[0],
                        "detail": detail_object.get("error_message", detail_object),
                        "code": detail_object.get("code"),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            else:
                raise

    @action(
        methods=["POST"],
        detail=False,
        url_path="coupons/claim",
        permission_classes=[permissions.IsAuthenticated, HasBillingAccess],
    )
    def claim_coupon(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        organization = self._get_org_required()

        code = request.data.get("code")
        if not code:
            raise ValidationError({"code": "This field is required."})

        billing_manager = self.get_billing_manager()

        try:
            res = billing_manager.claim_coupon(organization, {"code": code})
            return Response(res, status=status.HTTP_200_OK)
        except Exception as e:
            if len(e.args) > 2:
                detail_object = e.args[2]
                if not isinstance(detail_object, dict):
                    raise
                return Response(
                    {
                        "statusText": e.args[0],
                        "detail": detail_object.get("error_message") or detail_object.get("detail") or detail_object,
                        "code": detail_object.get("code"),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            else:
                raise

    @action(methods=["GET"], detail=False, url_path="coupons/overview")
    def coupons_overview(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = get_cached_instance_license()
        if not license:
            return Response({"claimed_coupons": []}, status=status.HTTP_200_OK)

        organization = self._get_org_required()
        billing_manager = self.get_billing_manager()
        res = billing_manager.coupons_overview(organization)
        return Response(res, status=status.HTTP_200_OK)

    @extend_schema(parameters=[BillingUsageRequestSerializer])
    @action(
        methods=["GET"],
        detail=False,
        url_path="usage",
        permission_classes=[permissions.IsAuthenticated, HasBillingUsageSpendReadAccess],
        responses={200: BillingTimeSeriesResponseSerializer},
    )
    def usage(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        return self._usage_or_spend_response(request, self.get_billing_manager().get_usage_data)

    @extend_schema(parameters=[BillingUsageRequestSerializer])
    @action(
        methods=["GET"],
        detail=False,
        url_path="spend",
        permission_classes=[permissions.IsAuthenticated, HasBillingUsageSpendReadAccess],
        responses={200: BillingTimeSeriesResponseSerializer},
    )
    def spend(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        """Endpoint to fetch spend data (proxy to billing service)."""
        return self._usage_or_spend_response(request, self.get_billing_manager().get_spend_data)

    def _usage_or_spend_response(
        self,
        request: Request,
        billing_data_getter: Callable[[Organization, dict[str, Any]], Any],
    ) -> HttpResponse:
        organization = self._get_org_required()
        serializer = BillingUsageRequestSerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)
        self._check_requested_team_ids_belong_to_org(organization, serializer.validated_data.get("team_ids"))

        try:
            params_to_pass = {k: v for k, v in serializer.validated_data.items() if v is not None}
            scoped_team_ids = self._scoped_team_ids_for_usage_spend_request(request, organization, params_to_pass)
            teams_map = self._get_teams_map(organization, scoped_team_ids)
            params_to_pass["teams_map"] = teams_map

            if scoped_team_ids is not None:
                params_to_pass["team_ids"] = json.dumps(scoped_team_ids)

            res = billing_data_getter(organization, params_to_pass)
            if scoped_team_ids is not None and isinstance(res, dict) and "team_id_options" in res:
                scoped_team_id_set = set(scoped_team_ids)
                res["team_id_options"] = [
                    team_id for team_id in (res.get("team_id_options") or []) if team_id in scoped_team_id_set
                ]
            return Response(res, status=status.HTTP_200_OK)
        except Exception as e:
            if len(e.args) > 2:
                detail_object = e.args[2]
                if not isinstance(detail_object, dict):
                    raise
                if detail_object.get("code") == "permission_denied":
                    # billing evaluates the same permission from its own cache, so flag rollout
                    # windows can still return a downstream permission denial.
                    raise PermissionDenied(HasBillingUsageSpendReadAccess.message)
                return Response(
                    {
                        "statusText": e.args[0],
                        "detail": detail_object.get("error_message", detail_object),
                        "code": detail_object.get("code"),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            else:
                raise

    def _scoped_team_ids_for_usage_spend_request(
        self, request: Request, organization: Organization, params_to_pass: dict[str, Any]
    ) -> Optional[Sequence[int]]:
        if not isinstance(request.user, User) or user_has_billing_access(request.user, organization):
            return None

        accessible_team_ids = self._team_ids_visible_to_user_in_org(request.user, organization)
        token_scoped_team_ids = get_authenticator_scoped_team_ids(getattr(request, "successful_authenticator", None))
        if token_scoped_team_ids is not None:
            accessible_team_ids = sorted(set(accessible_team_ids).intersection(token_scoped_team_ids))

        if not accessible_team_ids:
            raise PermissionDenied(HasBillingUsageSpendReadAccess.message)

        requested_team_ids = self._parse_team_ids(params_to_pass.get("team_ids"))
        if not requested_team_ids:
            return accessible_team_ids

        scoped_team_ids = sorted(set(requested_team_ids).intersection(accessible_team_ids))
        if not scoped_team_ids:
            raise PermissionDenied(HasBillingUsageSpendReadAccess.message)

        return scoped_team_ids

    def _team_ids_visible_to_user_in_org(self, user: User, organization: Organization) -> Sequence[int]:
        return list(
            visible_teams_for_user(
                organization,
                UserAccessControl(user=user, organization_id=str(organization.id)),
                UserPermissions(user=user),
            )
            .order_by("id")
            .values_list("id", flat=True)
        )

    def _parse_team_ids(self, team_ids: Optional[str]) -> Sequence[int]:
        if not team_ids:
            return []

        parsed_team_ids = json.loads(team_ids)
        if not isinstance(parsed_team_ids, list):
            raise ValidationError({"team_ids": "Value must be a JSON array of numeric team IDs."})

        return [team_id for team_id in parsed_team_ids if isinstance(team_id, int) and not isinstance(team_id, bool)]

    def _get_teams_map(self, organization: Organization, team_ids: Optional[Sequence[int]] = None) -> dict[int, str]:
        """
        Safely build a mapping of team.id to team.name for the org, optionally limited to team_ids.
        Return empty dict on failure.
        """
        try:
            teams = Team.objects.filter(organization=organization)
            if team_ids is not None:
                teams = teams.filter(id__in=team_ids)
            return {team.id: team.name for team in teams}
        except Exception as e:
            capture_exception(e, {"organization_id": organization.id})
            return {}

    def _check_requested_team_ids_belong_to_org(self, organization: Organization, team_ids: Optional[str]) -> None:
        if not team_ids:
            return

        requested_team_ids = set(json.loads(team_ids))
        if not requested_team_ids:
            return

        matching_team_ids = set(
            Team.objects.filter(organization=organization, id__in=requested_team_ids).values_list("id", flat=True)
        )

        if requested_team_ids != matching_team_ids:
            raise PermissionDenied("One or more requested projects are not in this organization.")

    def _get_org(self) -> Optional[Organization]:
        if self.request.user.is_anonymous:
            return None

        try:
            return self.team.organization
        except Exception:
            return None

    def _get_org_required(self) -> Organization:
        org = self._get_org()

        if not org:
            raise Exception("You cannot interact with the billing service without an organization configured.")

        return org
