from typing import Any, Optional, cast

import posthoganalytics
import requests
import structlog
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from ee.billing.billing_manager import BillingManager, build_billing_token
from ee.models import License
from ee.settings import BILLING_SERVICE_URL
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.cloud_utils import get_cached_instance_license
from posthog.event_usage import groups
from posthog.models import Organization
from posthog.models.user import User

logger = structlog.get_logger(__name__)

BILLING_SERVICE_JWT_AUD = "posthog:license-key"


class BillingSerializer(serializers.Serializer):
    plan = serializers.CharField(max_length=100)
    billing_limit = serializers.IntegerField()


class LicenseKeySerializer(serializers.Serializer):
    license = serializers.CharField()


class BillingViewset(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = BillingSerializer
    derive_current_team_from_user_only = True

    scope_object = "INTERNAL"

    def _can_manage_billing(self, request: Request, org: Organization) -> bool:
        return (
            not org.billing_access_level
            or request.user.organization_memberships.get(organization=org).level >= org.billing_access_level  # type: ignore
        )

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        license = get_cached_instance_license()
        if license and not license.is_v2_license:
            raise NotFound("Billing V2 is not supported for this license type")

        org = self._get_org()

        # If on Cloud and we have the property billing - return 404 as we always use legacy billing it it exists
        if hasattr(org, "billing"):
            if org.billing.stripe_subscription_id:  # type: ignore
                raise NotFound("Billing V1 is active for this organization")

        plan_keys = request.query_params.get("plan_keys", None)
        response = BillingManager(license).get_billing(org, plan_keys)

        if org and not self._can_manage_billing(request, org):
            # Don't show the portal URL if the user doesn't have access to billing
            response["stripe_portal_url"] = None

        return Response(response)

    @action(methods=["PATCH"], detail=False, url_path="/")
    def patch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        distinct_id = None if self.request.user.is_anonymous else self.request.user.distinct_id
        license = get_cached_instance_license()
        if not license:
            raise Exception("There is no license configured for this instance yet.")

        org = self._get_org_required()
        if not self._can_manage_billing(request, org):
            # Don't show the portal URL if the user doesn't have access to billing
            raise PermissionDenied("Your organization restricts access to billing information to admins only.")

        if license and org:  # for mypy
            custom_limits_usd = request.data.get("custom_limits_usd")
            if custom_limits_usd:
                BillingManager(license).update_billing(org, {"custom_limits_usd": custom_limits_usd})

                if distinct_id:
                    posthoganalytics.capture(
                        distinct_id,
                        "billing limits updated",
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

        return self.list(request, *args, **kwargs)

    @action(methods=["GET"], detail=False)
    def activation(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = get_cached_instance_license()
        organization = self._get_org_required()

        redirect_path = request.GET.get("redirect_path") or "organization/billing"
        if redirect_path.startswith("/"):
            redirect_path = redirect_path[1:]

        redirect_uri = f"{settings.SITE_URL or request.headers.get('Host')}/{redirect_path}"
        url = f"{BILLING_SERVICE_URL}/activation?redirect_uri={redirect_uri}&organization_name={organization.name}"

        plan = request.GET.get("plan", None)
        product_keys = request.GET.get("products", None)
        if not plan and not product_keys:
            # If no plan or product keys are specified, we default to the standard plan
            # This is to support the old activation flow
            plan = "standard"

        if plan:
            url = f"{url}&plan={plan}"
        if product_keys:
            url = f"{url}&products={product_keys}"

        if license:
            billing_service_token = build_billing_token(license, organization)
            url = f"{url}&token={billing_service_token}"

        return redirect(url)

    @action(methods=["GET"], detail=False)
    def deactivate(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = get_cached_instance_license()
        organization = self._get_org_required()

        product = request.GET.get("products", None)
        if not product:
            raise ValidationError("Products must be specified")
        try:
            BillingManager(license).deactivate_products(organization, product)
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
                raise e
        return self.list(request, *args, **kwargs)

    @action(methods=["GET"], detail=False)
    def get_invoices(self, request: Request, *args: Any, **kwargs: Any) -> HttpResponse:
        license = get_cached_instance_license()
        if not license:
            return Response(
                {"sucess": True},
                status=status.HTTP_200_OK,
            )

        organization = self._get_org_required()

        if not self._can_manage_billing(request, organization):
            raise PermissionDenied("Your organization restricts access to billing information to admins only.")

        invoice_status = request.GET.get("status")

        try:
            res = BillingManager(license).get_invoices(organization, status=invoice_status)
        except Exception as e:
            if len(e.args) > 2:
                detail_object = e.args[2]
                if not isinstance(detail_object, dict):
                    raise e
                return Response(
                    {
                        "statusText": e.args[0],
                        "detail": detail_object.get("error_message", detail_object),
                        "code": detail_object.get("code"),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            else:
                raise e

        return Response(
            {
                "link": res.get("portal_url"),
                "count": res.get("count"),
            },
            status=status.HTTP_200_OK,
        )

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

    def _get_org(self) -> Optional[Organization]:
        org = None if self.request.user.is_anonymous else self.request.user.organization

        return org

    def _get_org_required(self) -> Organization:
        org = self._get_org()

        if not org:
            raise Exception("You cannot interact with the billing service without an organization configured.")

        return org
