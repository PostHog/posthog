"""
Shared handler logic for the single-account endpoints called by the CDP worker's
workflow actions. Two routes delegate here: the legacy external route in
``external.py`` (team secret API token) and the JWT-only internal route in
``internal.py`` (#82564). The functions hold request validation and the mapping of
facade results to responses; auth stays in each route.
"""

import uuid
from typing import Any

from drf_spectacular.utils import extend_schema_field
from prometheus_client import Counter
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.models import Team

from products.customer_analytics.backend.facade import (
    api as facade,
    contracts,
)

ACCOUNT_ACTION_AUTH_COUNTER = Counter(
    "posthog_customer_analytics_account_action_auth_total",
    "Successful authentications on the account routes called by CDP workflow actions, by auth method",
    labelnames=["auth_method", "http_method"],  # auth_method: secret_api_token | scoped_jwt
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


def _external_account_body(account: contracts.ExternalAccount) -> dict[str, Any]:
    return {
        "id": account.id,
        "external_id": account.external_id,
        "name": account.name,
        "churned_at": account.churned_at,
        "ignored_at": account.ignored_at,
        "properties": account.properties,
        "tags": account.tags,
        "relationships": account.relationships,
        "custom_properties": account.custom_properties,
    }


_UPDATE_ERROR_RESPONSES = {
    contracts.ExternalAccountUpdateError.NOT_FOUND: ("Account not found", status.HTTP_404_NOT_FOUND),
    contracts.ExternalAccountUpdateError.INVALID_PROPERTIES: (
        "Invalid account properties",
        status.HTTP_400_BAD_REQUEST,
    ),
    # A server fault (the facade's blanket except), not a client error: 500 keeps the CDP
    # fetch layer retrying instead of failing the workflow permanently.
    contracts.ExternalAccountUpdateError.UPDATE_FAILED: (
        "Failed to update account",
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    ),
}


def _update_error_response(result: contracts.ExternalAccountUpdateResult) -> Response:
    if result.error == contracts.ExternalAccountUpdateError.USER_NOT_IN_ORGANIZATION:
        return Response(
            {"error": f"{result.error_field}: user is not a member of this organization"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if result.error == contracts.ExternalAccountUpdateError.RELATIONSHIP_DEFINITION_NOT_FOUND:
        return Response(
            {"error": f"{result.error_field}: no relationship definition with this ID"},
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
            "Relationship assignments keyed by definition UUID. Each value is an assignee object "
            "`{type: 'user', id}` or null to end the active assignment. Only the supplied "
            "definitions are changed."
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
    churned_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="When the account churned. Set to null to mark it as active again.",
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


class ExternalAccountCreateSerializer(serializers.Serializer):
    external_id = serializers.CharField(
        max_length=400,
        help_text=(
            "External ID (group key) for the account. An account with this ID already existing is a no-op. "
            "The account name is derived from the matching group's `name` property, falling back to this ID."
        ),
    )


@extend_schema_field({"oneOf": [{"type": "string"}, {"type": "number"}, {"type": "boolean"}, {"type": "null"}]})
class _CustomPropertyScalarField(serializers.Field):
    """A custom property value sent over the external API — a JSON scalar or null.

    The concrete type each property accepts is set by its definition and validated server-side when
    the value is coerced. Null clears the active value.
    """

    def to_internal_value(self, data: Any) -> Any:
        if isinstance(data, dict | list):
            raise serializers.ValidationError("Value must be a string, number, boolean, or null.")
        return data


class ExternalAccountCustomPropertiesSerializer(serializers.Serializer):
    external_id = serializers.CharField(
        max_length=400,
        help_text="External ID of the account whose custom property values to set — the group key it is linked to.",
    )
    properties = serializers.DictField(
        child=_CustomPropertyScalarField(allow_null=True),
        help_text=(
            "Map of custom property definition UUID to the value to set for this account. Use null to clear an "
            "active value. Omitted definitions are unchanged."
        ),
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


def handle_account_get(team: Team, external_id: str) -> Response:
    account = facade.get_external_account(team.id, external_id)
    if account is None:
        return Response({"error": "Account not found"}, status=status.HTTP_404_NOT_FOUND)

    return Response(_external_account_body(account))


def handle_account_create(request: Request, team: Team) -> Response:
    serializer = ExternalAccountCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
    data = serializer.validated_data

    external_id = data["external_id"].strip()
    if not external_id:
        return Response({"error": "external_id is required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        account, created = facade.create_external_account(
            team,
            external_id=external_id,
            workflow_id=_workflow_id_from_request(request),
        )
    except facade.AccountConflictError:
        # Lost a concurrent-create race; the account exists now, so honor no-op semantics.
        existing = facade.get_external_account(team.id, external_id)
        if existing is None:
            return Response({"error": "Failed to create account"}, status=status.HTTP_400_BAD_REQUEST)
        account, created = existing, False

    return Response(
        _external_account_body(account),
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


def handle_account_update(request: Request, team: Team) -> Response:
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
        churned_at=data.get("churned_at"),
        churned_at_provided="churned_at" in data,
        workflow_id=_workflow_id_from_request(request),
    )
    if result.account is None:
        return _update_error_response(result)

    return Response(_external_account_body(result.account))


def handle_account_set_properties(request: Request, team: Team) -> Response:
    serializer = ExternalAccountCustomPropertiesSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({"error": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
    data = serializer.validated_data

    external_id = data["external_id"].strip()
    if not external_id:
        return Response({"error": "external_id is required"}, status=status.HTTP_400_BAD_REQUEST)

    result = facade.set_external_account_custom_properties(
        team.id, external_id, properties=data["properties"], workflow_id=_workflow_id_from_request(request)
    )
    if result.values is None:
        return _custom_properties_error_response(result)

    # Hand-built payload, deliberately: neither wrapping route is in the OpenAPI spec (plain
    # APIViews without scope_object), so the schema-drift risk behind the rule cannot occur,
    # and the wire shape must stay identical while the worker migrates between the routes.
    return Response(  # nosemgrep: api-response-must-match-schema
        {
            "external_id": external_id,
            "values": [{"definition_id": str(v.definition_id), "value": v.value} for v in result.values],
        }
    )
