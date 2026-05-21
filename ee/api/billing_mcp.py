from typing import Any

from django.contrib.auth.models import AbstractUser

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.cloud_utils import get_cached_instance_license

from ee.billing.billing_manager import BillingManager


class BillingMCPViewset(TeamAndOrgViewSetMixin, GenericViewSet):
    """
    MCP-accessible read tools that proxy to billing's `/api/mcp/tools/` namespace.

    The billing service is the source of truth for role-based authorization:
    `BillingManager.get_auth_headers` builds a JWT that embeds the caller's
    `organization_role`, and billing's `IsOrgMember` / `IsOrgAdmin` / `IsOrgOwner`
    permission classes gate each tool. This viewset adds the OAuth/PAT scope
    gate (`billing:read`) so MCP clients are restricted at the PostHog edge as
    well, but the authoritative check lives in billing.
    """

    scope_object = "billing"
    param_derived_from_user_current_team = "team_id"

    def _get_billing_manager(self) -> BillingManager:
        license = get_cached_instance_license()
        user = (
            self.request.user if isinstance(self.request.user, AbstractUser) and self.request.user.distinct_id else None
        )
        return BillingManager(license, user)

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    @action(
        detail=False,
        methods=["GET"],
        url_path="billing-summary",
        required_scopes=["billing:read"],
    )
    def billing_summary(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        org = self._get_org()
        return Response(self._get_billing_manager().get_mcp_billing_summary(org))
