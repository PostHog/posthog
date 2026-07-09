"""
External API endpoints for the Customer analytics product.

These endpoints are used by the CDP worker for workflow actions. Authenticated
via the team secret API token passed as a Bearer token in the Authorization header.

The view holds only HTTP concerns — Bearer auth, throttles, the feature-flag gate,
request validation, and mapping facade results to responses. Data access, the
transactional write, org-membership resolution, tag application, and exception
capture live behind ``facade.api``.
"""

import uuid
import hashlib
from typing import Any

from django.db.models import Q

import structlog
import posthoganalytics
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from posthog.models import Team

from products.customer_analytics.backend.facade import (
    api as facade,
    contracts,
)
from products.customer_analytics.backend.facade.constants import CUSTOMER_ANALYTICS_CSP_FLAG

logger = structlog.get_logger(__name__)


class _ExternalAccountThrottle(SimpleRateThrottle):
    """Rate limit by Bearer token (team secret_api_token)."""

    def get_cache_key(self, request: Request, view: APIView) -> str:
        auth_header = request.headers.get("Authorization", "")
        token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
        ident = hashlib.sha256(token.encode()).hexdigest() if token else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class ExternalAccountBurstThrottle(_ExternalAccountThrottle):
    scope = "external_account_burst"
    rate = "60/minute"


class ExternalAccountSustainedThrottle(_ExternalAccountThrottle):
    scope = "external_account_sustained"
    rate = "600/hour"


def _customer_analytics_enabled(team: Team) -> bool:
    organization_id = str(team.organization_id)
    return bool(
        posthoganalytics.feature_enabled(
            CUSTOMER_ANALYTICS_CSP_FLAG,
            organization_id,
            groups={"organization": organization_id},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    )


HOG_FLOW_ID_HEADER = "X-PostHog-Hog-Flow-Id"


def _workflow_id_from_request(request: Request) -> str | None:
    """The originating HogFlow workflow id, when the request comes from a workflow step.

    The header is caller-supplied, so only a well-formed UUID is accepted; worst case is a
    token holder attributing a write to another workflow id within its own team.
    """
    hog_flow_id = request.headers.get(HOG_FLOW_ID_HEADER)
    if not hog_flow_id:
        return None
    try:
        uuid.UUID(hog_flow_id)
    except (ValueError, TypeError):
        return None
    return hog_flow_id


def _authenticate_team(request: Request) -> tuple[Team, None] | tuple[None, Response]:
    """Extract Bearer token from Authorization header and validate against a team."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, Response({"error": "Missing or invalid Authorization header"}, status=status.HTTP_401_UNAUTHORIZED)

    api_key = auth_header[7:].strip()
    if not api_key:
        return None, Response({"error": "Empty API key"}, status=status.HTTP_401_UNAUTHORIZED)

    # Authenticate against secret_api_token (not api_token) because api_token
    # is the public project key embedded in client-side JS and visible to anyone.
    try:
        team = Team.objects.get(Q(secret_api_token=api_key) | Q(secret_api_token_backup=api_key))
    except (Team.DoesNotExist, Team.MultipleObjectsReturned):
        return None, Response({"error": "Invalid API key"}, status=status.HTTP_401_UNAUTHORIZED)

    # Same 401 as an unknown token: a valid secret token for a team without customer
    # analytics enabled must not be usable to read account data.
    if not _customer_analytics_enabled(team):
        return None, Response({"error": "Invalid API key"}, status=status.HTTP_401_UNAUTHORIZED)

    return team, None


def _external_account_body(account: contracts.ExternalAccount) -> dict[str, Any]:
    return {
        "id": account.id,
        "external_id": account.external_id,
        "name": account.name,
        "properties": account.properties,
        "tags": account.tags,
        "relationships": account.relationships,
    }


_UPDATE_ERROR_RESPONSES = {
    contracts.ExternalAccountUpdateError.NOT_FOUND: ("Account not found", status.HTTP_404_NOT_FOUND),
    contracts.ExternalAccountUpdateError.INVALID_PROPERTIES: (
        "Invalid account properties",
        status.HTTP_400_BAD_REQUEST,
    ),
    contracts.ExternalAccountUpdateError.UPDATE_FAILED: ("Failed to update account", status.HTTP_400_BAD_REQUEST),
}


def _update_error_response(result: contracts.ExternalAccountUpdateResult) -> Response:
    if result.error == contracts.ExternalAccountUpdateError.USER_NOT_IN_ORGANIZATION:
        return Response(
            {"error": f"{result.error_field}: user is not a member of this organization"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if result.error == contracts.ExternalAccountUpdateError.RELATIONSHIP_DEFINITION_NOT_FOUND:
        return Response(
            {"error": f"{result.error_field}: no relationship definition with this name"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    assert result.error is not None
    message, code = _UPDATE_ERROR_RESPONSES[result.error]
    return Response({"error": message}, status=code)


class ExternalAccountUpdateSerializer(serializers.Serializer):
    external_id = serializers.CharField(max_length=400, help_text="External ID (group key) of the account to update.")
    # Each value accepts a `posthog_assignee` object `{type, id}`, or `null` to end the
    # active assignment. Roles (RBAC) are rejected — accounts assign users only.
    # `validate` normalizes a provided assignment down to the user id; the facade resolves
    # it against an org membership so assignees are always trusted.
    relationships = serializers.DictField(
        child=serializers.JSONField(allow_null=True),
        required=False,
        help_text=(
            "Relationship assignments keyed by definition name (e.g. 'CSM'). Each value is an "
            "assignee object `{type: 'user', id}` or null to end the active assignment. Only the "
            "named definitions are changed."
        ),
    )
    tags = serializers.ListField(
        child=serializers.CharField(max_length=200),
        required=False,
        max_length=100,
        help_text="Tag names to apply, per tags_mode.",
    )
    tags_mode = serializers.ChoiceField(
        choices=["add", "set", "remove"],
        required=False,
        default="add",
        help_text="How to apply tags: add to, replace, or remove from the existing set.",
    )

    def validate_relationships(self, value: dict[str, Any]) -> dict[str, int | None]:
        return {name: self._normalize_assignee(name, assignee) for name, assignee in value.items()}

    def _normalize_assignee(self, field: str, value: Any) -> int | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise serializers.ValidationError({field: "Must be an assignee object or null"})
        if value.get("type") != "user":
            raise serializers.ValidationError({field: "Accounts can only be assigned to users, not roles"})
        raw_id = value.get("id")
        if not isinstance(raw_id, (int, str)):
            raise serializers.ValidationError({field: "Assignee id must be a user id"})
        try:
            return int(raw_id)
        except (TypeError, ValueError):
            raise serializers.ValidationError({field: "Assignee id must be a user id"})


class ExternalAccountView(APIView):
    """
    GET /api/customer_analytics/external/account?external_id=<external_id> — Fetch account data
    PATCH /api/customer_analytics/external/account — Update an account's role contacts and tags

    Authenticated via Bearer token (team secret_api_token) in Authorization header.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ExternalAccountBurstThrottle, ExternalAccountSustainedThrottle]

    def get(self, request: Request) -> Response:
        team, error = _authenticate_team(request)
        if error:
            return error

        assert team is not None

        external_id = request.query_params.get("external_id", "").strip()
        if not external_id:
            return Response({"error": "external_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        account = facade.get_external_account(team.id, external_id)
        if account is None:
            return Response({"error": "Account not found"}, status=status.HTTP_404_NOT_FOUND)

        return Response(_external_account_body(account))

    def patch(self, request: Request) -> Response:
        team, error = _authenticate_team(request)
        if error:
            return error

        assert team is not None

        serializer = ExternalAccountUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data

        external_id = data["external_id"].strip()
        if not external_id:
            return Response({"error": "external_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        result = facade.update_external_account(
            team.id,
            external_id,
            relationship_assignments=data.get("relationships") or {},
            tags=data["tags"] if "tags" in data else None,
            tags_mode=data.get("tags_mode", "add"),
            workflow_id=_workflow_id_from_request(request),
        )
        if result.account is None:
            return _update_error_response(result)

        return Response(_external_account_body(result.account))


@extend_schema_field({"oneOf": [{"type": "string"}, {"type": "number"}, {"type": "boolean"}]})
class _CustomPropertyScalarField(serializers.Field):
    """A custom property value sent over the external API — a JSON scalar.

    Objects, arrays, and null are rejected here; the concrete type each property accepts is set by
    its definition and validated server-side when the value is coerced.
    """

    def to_internal_value(self, data: Any) -> Any:
        if data is None or isinstance(data, dict | list):
            raise serializers.ValidationError("Value must be a string, number, or boolean.")
        return data


class ExternalAccountCustomPropertiesSerializer(serializers.Serializer):
    external_id = serializers.CharField(
        max_length=400,
        help_text="External ID of the account whose custom property values to set — the group key it is linked to.",
    )
    properties = serializers.DictField(
        child=_CustomPropertyScalarField(),
        help_text="Map of custom property definition UUID to the value to set for this account.",
    )


_CUSTOM_PROPERTIES_ERROR_RESPONSES = {
    contracts.ExternalAccountCustomPropertiesError.ACCOUNT_NOT_FOUND: ("Account not found", status.HTTP_404_NOT_FOUND),
    contracts.ExternalAccountCustomPropertiesError.DEFINITION_NOT_FOUND: (
        "Custom property definition not found",
        status.HTTP_400_BAD_REQUEST,
    ),
    contracts.ExternalAccountCustomPropertiesError.INVALID_VALUE: (
        "Invalid custom property value",
        status.HTTP_400_BAD_REQUEST,
    ),
    contracts.ExternalAccountCustomPropertiesError.CONFLICT: (
        "A concurrent write set this property — retry",
        status.HTTP_409_CONFLICT,
    ),
    contracts.ExternalAccountCustomPropertiesError.UPDATE_FAILED: (
        "Failed to update custom properties",
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    ),
    contracts.ExternalAccountCustomPropertiesError.SOURCE_MANAGED: (
        "This custom property is managed by a data warehouse source and can't be set manually",
        status.HTTP_400_BAD_REQUEST,
    ),
}


def _custom_properties_error_response(result: contracts.ExternalAccountCustomPropertiesResult) -> Response:
    assert result.error is not None
    message, code = _CUSTOM_PROPERTIES_ERROR_RESPONSES[result.error]
    if result.error_field:
        message = f"{result.error_field}: {message}"
    return Response({"error": message}, status=code)


class ExternalAccountCustomPropertiesView(APIView):
    """
    PATCH /api/customer_analytics/external/account/custom_property_values — Set an account's custom
    property values, addressing each property by its definition id (UUID).

    Authenticated via Bearer token (team secret_api_token) in the Authorization header.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ExternalAccountBurstThrottle, ExternalAccountSustainedThrottle]

    @extend_schema(request=ExternalAccountCustomPropertiesSerializer, responses={200: OpenApiTypes.OBJECT})
    def patch(self, request: Request) -> Response:
        team, error = _authenticate_team(request)
        if error:
            return error

        assert team is not None

        serializer = ExternalAccountCustomPropertiesSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data

        external_id = data["external_id"].strip()
        if not external_id:
            return Response({"error": "external_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        result = facade.set_external_account_custom_properties(team.id, external_id, properties=data["properties"])
        if result.values is None:
            return _custom_properties_error_response(result)

        return Response(
            {
                "external_id": external_id,
                "values": [{"definition_id": str(v.definition_id), "value": v.value} for v in result.values],
            }
        )
