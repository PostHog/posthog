"""
DRF views for access_control.

Responsibilities:
- Validate incoming JSON (via serializers)
- Convert JSON to DTOs
- Call facade methods
- Convert DTOs to JSON responses

No business logic or ORM access here — that belongs in the facade / logic layer.
"""

from typing import Any

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.constants import AvailableFeature
from posthog.permissions import TeamMemberStrictManagementPermission

from ..facade import api
from ..facade.contracts import DeletePropertyAccessControlInput, PropertyAccessLevel, UpsertPropertyAccessControlInput
from .serializers import (
    PropertyAccessControlDeleteSerializer,
    PropertyAccessControlRuleSerializer,
    PropertyAccessControlStateSerializer,
    PropertyAccessControlUpdateSerializer,
)

PROPERTY_ACCESS_CONTROL_FEATURE_REQUIRED_MESSAGE = "Property access control feature is required"


class _SingletonStateSchema(AutoSchema):
    """Prevents drf-spectacular from wrapping the ``list`` response in an array.

    The GET endpoint returns an aggregate ``PropertyAccessControlState`` object,
    not a paginated/collection list.
    """

    def _is_list_view(self, serializer: object = None) -> bool:
        return False


class PropertyAccessControlViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    """
    Manages property-level access control rules for property definitions.

    Mounted at `/api/environments/{team_id}/property_access_controls/`. The target
    property definition is provided via the `property_definition_id` query parameter
    on GET requests and in the request body on POST requests.
    """

    scope_object = "access_control"
    serializer_class = PropertyAccessControlRuleSerializer
    permission_classes = [TeamMemberStrictManagementPermission]
    # The list endpoint returns an aggregate state object, not a paginated
    # collection. Disable pagination and tell drf-spectacular not to wrap
    # the response schema in an array, so the generated OpenAPI — and the
    # downstream TypeScript / MCP types — reflect the actual response shape.
    pagination_class = None
    schema = _SingletonStateSchema()

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="property_definition_id",
                description="The property definition ID to fetch access control rules for.",
                required=True,
                type=str,
            ),
        ],
        responses={200: PropertyAccessControlStateSerializer},
        description="Get all property access control rules for a property definition.",
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        property_definition_id = request.query_params.get("property_definition_id")
        if not property_definition_id:
            raise ValidationError({"property_definition_id": "This query parameter is required."})

        try:
            state = api.get_property_access_state(
                team_id=self.team_id,
                property_definition_id=property_definition_id,
            )
        except api.PropertyDefinitionNotFoundError:
            raise NotFound("Property definition not found.")

        return Response(PropertyAccessControlStateSerializer(state).data)

    @extend_schema(
        request=PropertyAccessControlUpdateSerializer,
        responses={200: PropertyAccessControlRuleSerializer},
        description="Create or update a property access control rule.",
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if not self.organization.is_feature_available(AvailableFeature.PROPERTY_ACCESS_CONTROL):
            raise PermissionDenied(PROPERTY_ACCESS_CONTROL_FEATURE_REQUIRED_MESSAGE)

        serializer = PropertyAccessControlUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        created_by_id: int | None = request.user.pk if request.user.is_authenticated else None
        try:
            rule = api.upsert_property_access_control(
                team_id=self.team_id,
                created_by_id=created_by_id,
                input=UpsertPropertyAccessControlInput(
                    property_definition_id=data["property_definition_id"],
                    access_level=PropertyAccessLevel(data["access_level"]),
                    organization_member_id=data.get("organization_member"),
                    role_id=data.get("role"),
                ),
            )
        except api.PropertyDefinitionNotFoundError:
            raise NotFound("Property definition not found.")
        except api.InvalidPropertyAccessControlTargetError as exc:
            raise ValidationError(str(exc))

        return Response(
            PropertyAccessControlRuleSerializer(rule).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="property_definition_id",
                description="The property definition ID the rule applies to.",
                required=True,
                type=str,
            ),
            OpenApiParameter(
                name="organization_member",
                description="The organization member UUID whose override should be deleted.",
                required=False,
                type=str,
            ),
            OpenApiParameter(
                name="role",
                description="The role UUID whose override should be deleted.",
                required=False,
                type=str,
            ),
        ],
        responses={204: None},
        description=(
            "Delete a property access control rule. The rule is identified by "
            "`property_definition_id` plus an optional `organization_member` or "
            "`role` query parameter. Omitting both targets deletes the default rule."
        ),
    )
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if not self.organization.is_feature_available(AvailableFeature.PROPERTY_ACCESS_CONTROL):
            raise PermissionDenied(PROPERTY_ACCESS_CONTROL_FEATURE_REQUIRED_MESSAGE)

        serializer = PropertyAccessControlDeleteSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            api.delete_property_access_control(
                team_id=self.team_id,
                input=DeletePropertyAccessControlInput(
                    property_definition_id=data["property_definition_id"],
                    organization_member_id=data.get("organization_member"),
                    role_id=data.get("role"),
                ),
            )
        except api.PropertyDefinitionNotFoundError:
            raise NotFound("Property definition not found.")
        except api.PropertyAccessControlRuleNotFoundError:
            raise NotFound("Property access control rule not found.")
        except api.InvalidPropertyAccessControlTargetError as exc:
            raise ValidationError(str(exc))

        return Response(status=status.HTTP_204_NO_CONTENT)
