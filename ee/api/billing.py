import json
from typing import Any, Optional
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.http import HttpResponse
from django.shortcuts import redirect

import requests
import structlog
import posthoganalytics
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.cloud_utils import get_cached_instance_license
from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.models import Organization, Team
from posthog.models.organization import OrganizationMembership
from posthog.utils import relative_date_parse

from ee.billing.billing_manager import BillingManager, build_billing_token
from ee.models import License
from ee.settings import BILLING_SERVICE_URL

logger = structlog.get_logger(__name__)

BILLING_SERVICE_JWT_AUD = "posthog:license-key"


class IsOrganizationAdmin(permissions.BasePermission):
    """
    Permission to allow only organization admins (level >= ADMIN) to access billing endpoints.
    """

    def has_permission(self, request, view):
        try:
            org = view._get_org_required()
        except Exception:
            return False
        return OrganizationMembership.objects.filter(
            user=request.user, organization=org, level__gte=OrganizationMembership.Level.ADMIN
        ).exists()


class BillingSerializer(serializers.Serializer):
    plan = serializers.CharField(max_length=100)
    billing_limit = serializers.IntegerField()


class LicenseKeySerializer(serializers.Serializer):
    license = serializers.CharField()


class BillingUsageRequestSerializer(serializers.Serializer):
    """
    Serializer for the usage and spend requests to the billing service.
    Only responsible for parsing dates, passes through other params.
    """

    start_date = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    end_date = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    usage_types = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    team_ids = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    breakdowns = serializers.CharField(required=False, allow_blank=True, allow_null=True)
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


class BillingViewset(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = BillingSerializer
    param_derived_from_user_current_team = "team_id"

    scope_object = "INTERNAL"

    def get_billing_manager(self) -> BillingManager:
        license = get_cached_instance_license()
        user = (
            self.request.user if isinstance(self.request.user, AbstractUser) and self.request.user.distinct_id else None
        )
        return BillingManager(license, user)

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        license = get_cached_instance_license()
        if license and not license.is_v2_license:
            raise NotFound("Billing is not supported for this license type")

        org = self._get_org()

        # If on Cloud and we have the property billing - return 404 as we always use legacy billing it it exists
        if hasattr(org, "billing"):
            if org.billing.stripe_subscription_id:  # type: ignore
                raise NotFound("Billing V1 is active for this organization")

        billing_manager = self.get_billing_manager()
        query = {}
        if "include_forecasting" in request.query_params:
            query["include_forecasting"] = request.query_params.get("include_forecasting")
        response = billing_manager.get_billing(org, query)

        return Response(response)

    @action(methods=["PATCH"], detail=False, url_path="/")
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

    class ActivateSerializer(serializers.Serializer):
        plan = serializers.CharField(required=False)
        products = serializers.CharField(
            required=False
        )  # This is required but in order to support an error for the legacy 'plan' param we need to set required=False
        redirect_path = serializers.CharField(required=False)
        intent_product = serializers.CharField(required=False)

        def validate(self, data):
            plan = data.get("plan")
            products = data.get("products")

            if plan and not products:
                raise ValidationError(
                    {
                        "plan": "The 'plan' parameter is no longer supported. Please use the 'products' parameter instead."
                    }
                )
            if not products:
                raise ValidationError({"products": "The 'products' parameter is required."})

            return data

    # This is deprecated and should be removed in the future in favor of 'activate'
    @action(methods=["GET"], detail=False)
    def activation(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        return self.handle_activate(request, *args, **kwargs)

    @action(methods=["GET"], detail=False)
    def activate(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        return self.handle_activate(request, *args, **kwargs)

    # A viewset action cannot call another action directly so this is in place until
    # the 'activation' endpoint is removed. Once removed, this method can move to the 'activate' action
    def handle_activate(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = get_cached_instance_license()
        organization = self._get_org_required()

        serializer = self.ActivateSerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)

        redirect_path = serializer.validated_data.get("redirect_path", "organization/billing")
        if redirect_path.startswith("/"):
            redirect_path = redirect_path[1:]

        redirect_uri = f"{settings.SITE_URL or request.headers.get('Host')}/{redirect_path}"
        url = f"{BILLING_SERVICE_URL}/activate?redirect_uri={redirect_uri}&organization_name={organization.name}"

        products = serializer.validated_data.get("products")
        url = f"{url}&products={products}"

        intent_product = serializer.validated_data.get("intent_product")
        if intent_product:
            url = f"{url}&intent_product={intent_product}"

        if license:
            billing_service_token = build_billing_token(license, organization)
            url = f"{url}&token={billing_service_token}"

        return redirect(url)

    class DeactivateSerializer(serializers.Serializer):
        products = serializers.CharField()

    @action(methods=["GET"], detail=False)
    def deactivate(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        organization = self._get_org_required()

        serializer = self.DeactivateSerializer(data=request.GET)
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

    @action(methods=["GET"], detail=False)
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

    @action(methods=["POST"], detail=False, url_path="credits/purchase")
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

    @action(methods=["POST"], detail=False, url_path="trials/activate")
    def activate_trial(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        organization = self._get_org_required()
        billing_manager = self.get_billing_manager()
        res = billing_manager.activate_trial(organization, request.data)
        return Response(res, status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=False, url_path="trials/cancel")
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

    @action(methods=["PATCH"], detail=False)
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
        res = requests.get(
            f"{BILLING_SERVICE_URL}/api/billing",
            headers=BillingManager(license).get_auth_headers(organization),
        )

        if res.status_code != 200:
            raise ValidationError(
                {
                    "license": f"License could not be activated. Please contact support. (BillingService status {res.status_code})",
                }
            )
        data = res.json()
        BillingManager(license).update_license_details(data)
        return Response({"success": True})

    @action(methods=["POST"], detail=False, url_path="startups/apply")
    def apply_startup_program(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        user = self.request.user
        if not isinstance(user, AbstractUser):
            raise PermissionDenied("You must be logged in to apply for the startup program")

        organization_id = request.data.get("organization_id")
        if not organization_id:
            raise ValidationError({"organization_id": "This field is required."})

        organization = Organization.objects.get(id=organization_id)
        if not organization:
            raise ValidationError({"organization_id": "Organization not found."})

        membership = OrganizationMembership.objects.get(user=user, organization=organization)
        if membership.level < OrganizationMembership.Level.ADMIN:
            raise PermissionDenied("You need to be an organization admin or owner to apply for the startup program")

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
        methods=["GET"],
        detail=False,
        url_path="usage",
        permission_classes=[permissions.IsAuthenticated, IsOrganizationAdmin],
    )
    def usage(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        organization = self._get_org_required()
        billing_manager = self.get_billing_manager()

        serializer = BillingUsageRequestSerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)

        teams_map = self._get_teams_map(organization)

        try:
            params_to_pass = {k: v for k, v in serializer.validated_data.items() if v is not None}
            params_to_pass["organization_id"] = organization.id
            params_to_pass["teams_map"] = json.dumps(teams_map)
            res = billing_manager.get_usage_data(organization, params_to_pass)
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
        methods=["GET"],
        detail=False,
        url_path="spend",
        permission_classes=[permissions.IsAuthenticated, IsOrganizationAdmin],
    )
    def spend(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        """Endpoint to fetch spend data (proxy to billing service)."""
        organization = self._get_org_required()
        billing_manager = self.get_billing_manager()

        serializer = BillingUsageRequestSerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)

        teams_map = self._get_teams_map(organization)

        try:
            params_to_pass = {k: v for k, v in serializer.validated_data.items() if v is not None}
            params_to_pass["organization_id"] = organization.id
            params_to_pass["teams_map"] = json.dumps(teams_map)
            res = billing_manager.get_spend_data(organization, params_to_pass)
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

    def _get_teams_map(self, organization: Organization) -> dict[int, str]:
        """
        Safely build a mapping of team.id to team.name for the org. Return empty dict on failure.
        """
        try:
            return {team.id: team.name for team in Team.objects.filter(organization=organization)}
        except Exception as e:
            capture_exception(e, {"organization_id": organization.id})
            return {}

    def _get_org(self) -> Optional[Organization]:
        org = None if self.request.user.is_anonymous else self.request.user.organization

        return org

    def _get_org_required(self) -> Organization:
        org = self._get_org()

        if not org:
            raise Exception("You cannot interact with the billing service without an organization configured.")

        return org
