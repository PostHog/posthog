"""Expose a team's quota-limit state.

Backs the LLM gateway's `QuotaResolver`, which forwards the caller's auth
header here to learn whether a given team is currently over its AI credits
quota. Project-nested so org membership and token `scoped_teams`/
`scoped_organizations` enforcement come from the standard
`TeamAndOrgViewSetMixin` permission chain — see
`posthog.permissions.APIScopePermission.check_team_and_org_permissions`.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited


class QuotaResourceLimitSerializer(serializers.Serializer):
    limited = serializers.BooleanField(
        help_text="True when the team is currently over its quota for this resource and limits are in effect.",
    )


class QuotaLimitsResponseSerializer(serializers.Serializer):
    limited = serializers.DictField(
        child=QuotaResourceLimitSerializer(),
        help_text=(
            "Per-resource limit state keyed by `QuotaResource` value. "
            "Currently only `ai_credits` is reported; additional resources may be added."
        ),
    )


@extend_schema(tags=["quota_limits"])
class QuotaLimitsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Read-only view of a team's quota-limit state."""

    scope_object = "project"
    required_scopes = ["project:read"]
    http_method_names = ["get", "head", "options"]

    @extend_schema(
        summary="Get a team's quota-limit state",
        description=(
            "Return the current quota-limit state for the team identified in the URL, "
            "keyed by `QuotaResource` value. Used by the LLM gateway to gate billable "
            "products on AI credits exhaustion."
        ),
        responses={200: QuotaLimitsResponseSerializer},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        limited = {
            resource.value: {
                "limited": is_team_limited(
                    self.team.api_token,
                    resource,
                    QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY,
                ),
            }
            for resource in QuotaResource
        }
        return Response(QuotaLimitsResponseSerializer({"limited": limited}).data)
