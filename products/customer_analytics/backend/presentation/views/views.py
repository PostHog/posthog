"""DRF views for the customer_analytics account CRUD endpoints.

Thin HTTP layer: these viewsets validate requests, gate access through the standard
mixins, and shape responses, but reach all product data through the facade — no product
models are imported here. Request validation, status codes, ``@extend_schema`` parameter
declarations, pagination wiring, and the markdown→tiptap normalization for account
notebooks stay here; team/object access filtering, transactions, conflict handling,
pydantic-error formatting, and activity logging live behind the facade.
"""

# Lazy annotations: each ViewSet defines a ``list`` method, which would otherwise shadow the
# ``list`` builtin for any ``list[...]`` annotation evaluated later in the same class body.
from __future__ import annotations

import json
from dataclasses import asdict
from typing import cast
from uuid import UUID

from django.db import transaction

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.tagged_item import TaggedItemViewSetMixin
from posthog.exceptions import Conflict
from posthog.helpers.impersonation import is_impersonated
from posthog.models.user import User
from posthog.permissions import is_service_auth
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin

from products.customer_analytics.backend.facade import api, contracts
from products.customer_analytics.backend.logic import event_stream_destination
from products.customer_analytics.backend.presentation.views.serializers import (
    AccountNotebookSerializer,
    AccountNoteSerializer,
    AccountRelationshipDefinitionSerializer,
    AccountRelationshipSerializer,
    AccountRelationshipWriteSerializer,
    AccountSerializer,
    CustomerJourneySerializer,
    CustomerProfileConfigSerializer,
    CustomPropertyDefinitionSerializer,
    CustomPropertySourceSerializer,
    CustomPropertySourceUpdateSerializer,
    CustomPropertyValueSerializer,
    CustomPropertyValueSuggestionsResponseSerializer,
    CustomPropertyValueWriteSerializer,
    EventStreamMemberWriteSerializer,
    EventStreamSerializer,
)

from ee.hogai.tools.create_notebook.tiptap import markdown_to_tiptap_nodes

# Object-level access levels for the resource ViewSets, matching what
# ``AccessControlPermission._get_required_access_level`` derives for these scope objects:
# reads need "viewer", writes need "editor".
_OBJECT_READ_LEVEL = "viewer"
_OBJECT_WRITE_LEVEL = "editor"

# drf-spectacular auto-describes the pk path param for a model-backed viewset as
# "A UUID string identifying this <model>.". These viewsets reach the model through the
# facade (no ``queryset``), so the description is declared explicitly to keep the generated
# OpenAPI (and MCP) path params byte-identical.
_ACCOUNT_ID_PARAM = OpenApiParameter(
    "id",
    OpenApiTypes.STR,
    OpenApiParameter.PATH,
    description="A UUID string identifying this account.",
)


# NOTE: deliberately no class docstring — a docstring here is inherited as the ViewSets'
# ``__doc__`` and drf-spectacular would surface it as every operation's description (the
# model-backed viewsets had none), drifting the generated clients.
class _FacadePaginationMixin:
    # Drives the standard ``LimitOffsetPagination`` envelope from a facade ``(page, count)``
    # result. The facade does the slicing (offset/limit), so we set the paginator's state
    # directly rather than handing it a queryset — keeping the param names (``limit`` /
    # ``offset``), default page size, and ``count`` / ``next`` / ``previous`` shape identical
    # to the model-backed viewsets.
    def _paginate_via_facade(self, request: Request, fetch, serializer_class) -> Response:
        paginator = self.paginator  # type: ignore[attr-defined]
        limit = paginator.get_limit(request)
        offset = paginator.get_offset(request)
        page, count = fetch(offset=offset, limit=limit)
        paginator.request = request
        paginator.limit = limit
        paginator.offset = offset
        paginator.count = count
        serializer = serializer_class(instance=page, many=True)
        return paginator.get_paginated_response(serializer.data)


def _object_required_level(request: Request, write: bool) -> str | None:
    """The object-level access level to enforce for this request, or ``None`` when the
    permission layer would skip the object check (service auth) — mirroring
    ``AccessControlPermission.has_object_permission``."""
    if is_service_auth(request):
        return None
    return _OBJECT_WRITE_LEVEL if write else _OBJECT_READ_LEVEL


class CustomerProfileConfigViewSet(
    TeamAndOrgViewSetMixin,
    _FacadePaginationMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "customer_profile_config"
    serializer_class = CustomerProfileConfigSerializer
    queryset = None  # data is reached through the facade; declared for router/schema only

    def list(self, request: Request, *args, **kwargs) -> Response:
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_customer_profile_configs(self.team_id, offset=offset, limit=limit),
            CustomerProfileConfigSerializer,
        )

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        config = api.get_customer_profile_config(self.team_id, self.kwargs["pk"])
        if config is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CustomerProfileConfigSerializer(instance=config).data)

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = CustomerProfileConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        config = api.create_customer_profile_config(
            team_id=self.team_id,
            scope=data.scope,
            content=data.content,
            sidebar=data.sidebar,
            organization_id=self.organization.id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
        )
        return Response(CustomerProfileConfigSerializer(instance=config).data, status=status.HTTP_201_CREATED)

    def update(self, request: Request, *args, **kwargs) -> Response:
        partial = kwargs.pop("partial", False)
        serializer = CustomerProfileConfigSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        config = api.update_customer_profile_config(
            team_id=self.team_id,
            config_id=self.kwargs["pk"],
            fields=_profile_config_write_fields(serializer.validated_data, request.data),
            organization_id=self.organization.id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
        )
        if config is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CustomerProfileConfigSerializer(instance=config).data)

    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        deleted = api.delete_customer_profile_config(
            team_id=self.team_id,
            config_id=self.kwargs["pk"],
            organization_id=self.organization.id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
        )
        if not deleted:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _profile_config_write_fields(validated, raw_data: dict) -> dict:
    """The profile-config columns the caller actually sent (scope/content/sidebar). ``content``
    and ``sidebar`` default to ``{}`` in the serializer, so only forward them when present in
    the raw body — matching the model serializer's partial-update behavior."""
    fields: dict = {}
    if "scope" in raw_data:
        fields["scope"] = validated.scope
    if "content" in raw_data:
        fields["content"] = validated.content
    if "sidebar" in raw_data:
        fields["sidebar"] = validated.sidebar
    return fields


class CustomPropertyDefinitionViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    _FacadePaginationMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "account"
    serializer_class = CustomPropertyDefinitionSerializer
    queryset = None  # data is reached through the facade; declared for router/schema only

    def list(self, request: Request, *args, **kwargs) -> Response:
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_custom_property_definitions(
                self.team_id, offset=offset, limit=limit, user_access_control=self.user_access_control
            ),
            CustomPropertyDefinitionSerializer,
        )

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        definition = api.get_custom_property_definition(
            self.team_id, self.kwargs["pk"], user_access_control=self.user_access_control
        )
        if definition is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CustomPropertyDefinitionSerializer(instance=definition).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="key",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Id of the custom property definition to suggest values for.",
            ),
            OpenApiParameter(
                name="value",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Case-insensitive substring to narrow the suggestions.",
            ),
        ],
        responses={200: CustomPropertyValueSuggestionsResponseSerializer},
    )
    @action(methods=["GET"], detail=False, pagination_class=None)
    def values(self, request: Request, *args, **kwargs) -> Response:
        key = request.GET.get("key")
        if not key:
            return Response({"results": [], "refreshing": False})
        suggestions = api.list_custom_property_value_suggestions(self.team_id, key, request.GET.get("value"))
        return Response({"results": [{"name": value} for value in suggestions], "refreshing": False})

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = CustomPropertyDefinitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            definition = api.create_custom_property_definition(
                team_id=self.team_id,
                name=data.name,
                description=data.description,
                display_type=data.display_type,
                is_big_number=data.is_big_number,
                options=_custom_property_option_dicts(data.options),
                organization_id=self.organization.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
            )
        except api.CustomPropertyDefinitionConflictError as e:
            raise Conflict(str(e))
        except api.InvalidCustomPropertyOptions as e:
            raise ValidationError({"options": str(e)})
        return Response(CustomPropertyDefinitionSerializer(instance=definition).data, status=status.HTTP_201_CREATED)

    def update(self, request: Request, *args, **kwargs) -> Response:
        partial = kwargs.pop("partial", False)
        serializer = CustomPropertyDefinitionSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            definition = api.update_custom_property_definition(
                team_id=self.team_id,
                definition_id=self.kwargs["pk"],
                fields=_custom_property_definition_write_fields(serializer.validated_data, request.data),
                organization_id=self.organization.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
            )
        except api.CustomPropertyDefinitionConflictError as e:
            raise Conflict(str(e))
        except api.InvalidCustomPropertyOptions as e:
            raise ValidationError({"options": str(e)})
        if definition is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CustomPropertyDefinitionSerializer(instance=definition).data)

    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        deleted = api.delete_custom_property_definition(
            team_id=self.team_id,
            definition_id=self.kwargs["pk"],
            organization_id=self.organization.id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
        )
        if not deleted:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _custom_property_definition_write_fields(validated, raw_data: dict) -> dict:
    """The columns the caller actually sent. ``is_big_number`` is re-derived in the facade against
    the effective display type, so a PATCH that omits it still clears it for a non-numeric type."""
    fields: dict = {}
    if "name" in raw_data:
        fields["name"] = validated.name
    if "description" in raw_data:
        fields["description"] = validated.description
    if "display_type" in raw_data:
        fields["display_type"] = validated.display_type
    if "is_big_number" in raw_data:
        fields["is_big_number"] = validated.is_big_number
    if "options" in raw_data:
        fields["options"] = _custom_property_option_dicts(validated.options)
    return fields


def _custom_property_option_dicts(options) -> list[dict] | None:
    """Nested DataclassSerializer fields validate into dataclass instances; the facade and the
    JSONField speak plain dicts."""
    if options is None:
        return None
    return [asdict(option) for option in options]


class AccountRelationshipDefinitionViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    _FacadePaginationMixin,
    viewsets.ModelViewSet,
):
    scope_object = "account"
    serializer_class = AccountRelationshipDefinitionSerializer
    queryset = None  # data is reached through the facade; declared for router/schema only

    def list(self, request: Request, *args, **kwargs) -> Response:
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_account_relationship_definitions(self.team_id, offset=offset, limit=limit),
            AccountRelationshipDefinitionSerializer,
        )

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        definition = api.get_account_relationship_definition(self.team_id, self.kwargs["pk"])
        if definition is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AccountRelationshipDefinitionSerializer(instance=definition).data)

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = AccountRelationshipDefinitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            definition = api.create_account_relationship_definition(
                team_id=self.team_id,
                name=data.name,
                description=data.description,
                is_single_holder=data.is_single_holder,
                created_by=cast(User, request.user),
            )
        except api.AccountRelationshipDefinitionConflictError as e:
            raise Conflict(str(e))
        return Response(
            AccountRelationshipDefinitionSerializer(instance=definition).data, status=status.HTTP_201_CREATED
        )

    def update(self, request: Request, *args, **kwargs) -> Response:
        partial = kwargs.pop("partial", False)
        serializer = AccountRelationshipDefinitionSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            definition = api.update_account_relationship_definition(
                team_id=self.team_id,
                definition_id=self.kwargs["pk"],
                fields=_account_relationship_definition_write_fields(serializer.validated_data, request.data),
            )
        except api.AccountRelationshipDefinitionConflictError as e:
            raise Conflict(str(e))
        if definition is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AccountRelationshipDefinitionSerializer(instance=definition).data)

    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        if not api.delete_account_relationship_definition(team_id=self.team_id, definition_id=self.kwargs["pk"]):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _account_relationship_definition_write_fields(validated, raw_data: dict) -> dict:
    fields: dict = {}
    if "name" in raw_data:
        fields["name"] = validated.name
    if "description" in raw_data:
        fields["description"] = validated.description
    if "is_single_holder" in raw_data:
        fields["is_single_holder"] = validated.is_single_holder
    return fields


class CustomPropertySourceViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    _FacadePaginationMixin,
    viewsets.ModelViewSet,
):
    scope_object = "account"
    serializer_class = CustomPropertySourceSerializer
    queryset = None  # data is reached through the facade; declared for router/schema only

    def list(self, request: Request, *args, **kwargs) -> Response:
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_custom_property_sources(self.team_id, offset=offset, limit=limit),
            CustomPropertySourceSerializer,
        )

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        source = api.get_custom_property_source(self.team_id, self.kwargs["pk"])
        if source is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CustomPropertySourceSerializer(instance=source).data)

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = CustomPropertySourceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            source = api.create_custom_property_source(
                team_id=self.team_id,
                definition_id=data.definition,
                saved_query_id=data.saved_query,
                source_column=data.source_column,
                key_column=data.key_column,
                is_enabled=data.is_enabled,
                user=cast(User, request.user),
            )
        except api.CustomPropertySourceValidationError as e:
            raise ValidationError(str(e))
        return Response(CustomPropertySourceSerializer(instance=source).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=CustomPropertySourceUpdateSerializer)
    def update(self, request: Request, *args, **kwargs) -> Response:
        write = CustomPropertySourceUpdateSerializer(data=request.data, partial=kwargs.pop("partial", False))
        write.is_valid(raise_exception=True)
        source = api.update_custom_property_source(
            team_id=self.team_id, source_id=self.kwargs["pk"], fields=write.validated_data
        )
        if source is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CustomPropertySourceSerializer(instance=source).data)

    @extend_schema(request=CustomPropertySourceUpdateSerializer)
    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        deleted = api.delete_custom_property_source(team_id=self.team_id, source_id=self.kwargs["pk"])
        if not deleted:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CustomerJourneyViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    _FacadePaginationMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "customer_journey"
    serializer_class = CustomerJourneySerializer
    queryset = None

    def list(self, request: Request, *args, **kwargs) -> Response:
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_customer_journeys(
                self.team_id, offset=offset, limit=limit, user_access_control=self.user_access_control
            ),
            CustomerJourneySerializer,
        )

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        try:
            journey = api.get_customer_journey(
                self.team_id,
                self.kwargs["pk"],
                user_access_control=self.user_access_control,
                required_level=_object_required_level(request, write=False),
            )
        except api.CustomerJourney_DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except api.ResourceForbiddenError:
            raise PermissionDenied()
        return Response(CustomerJourneySerializer(instance=journey).data)

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = CustomerJourneySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if not api.insight_belongs_to_team(self.team_id, data.insight):
            raise ValidationError({"insight": "The insight does not belong to this team."})
        try:
            journey = api.create_customer_journey(
                team_id=self.team_id,
                insight_id=data.insight,
                name=data.name,
                description=data.description,
                organization_id=self.organization.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
            )
        except api.CustomerJourneyConflictError as e:
            raise Conflict(str(e))
        return Response(CustomerJourneySerializer(instance=journey).data, status=status.HTTP_201_CREATED)

    def update(self, request: Request, *args, **kwargs) -> Response:
        partial = kwargs.pop("partial", False)
        serializer = CustomerJourneySerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "insight" in request.data and not api.insight_belongs_to_team(self.team_id, data.insight):
            raise ValidationError({"insight": "The insight does not belong to this team."})
        try:
            journey = api.update_customer_journey(
                team_id=self.team_id,
                journey_id=self.kwargs["pk"],
                fields=_journey_write_fields(data, request.data),
                user_access_control=self.user_access_control,
                required_level=_object_required_level(request, write=True),
                organization_id=self.organization.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
            )
        except api.CustomerJourney_DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except api.ResourceForbiddenError:
            raise PermissionDenied()
        return Response(CustomerJourneySerializer(instance=journey).data)

    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        try:
            api.delete_customer_journey(
                team_id=self.team_id,
                journey_id=self.kwargs["pk"],
                user_access_control=self.user_access_control,
                required_level=_object_required_level(request, write=True),
                organization_id=self.organization.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
            )
        except api.CustomerJourney_DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except api.ResourceForbiddenError:
            raise PermissionDenied()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _journey_write_fields(validated, raw_data: dict) -> dict:
    fields: dict = {}
    if "name" in raw_data:
        fields["name"] = validated.name
    if "description" in raw_data:
        fields["description"] = validated.description
    if "insight" in raw_data:
        fields["insight_id"] = validated.insight
    return fields


def _parse_tags_param(request: Request) -> list[str] | None:
    tags_param = request.query_params.get("tags")
    if not tags_param:
        return None
    try:
        tags_list = json.loads(tags_param)
    except json.JSONDecodeError:
        raise ValidationError({"tags": "Must be a JSON-encoded list of strings."})
    if not isinstance(tags_list, list) or not all(isinstance(t, str) for t in tags_list):
        raise ValidationError({"tags": "Must be a JSON-encoded list of strings."})
    return tags_list


class AccountViewSet(
    TaggedItemViewSetMixin,
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    _FacadePaginationMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "account"
    serializer_class = AccountSerializer
    queryset = None
    bulk_update_tags = None  # Mixin action assumes integer PKs; Account uses UUIDs.

    ALLOWED_ORDERING = frozenset({"name", "-name", "created_at", "-created_at", "updated_at", "-updated_at"})

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="search",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Case-insensitive substring search across account name and external ID.",
            ),
            OpenApiParameter(
                name="tags",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    'JSON-encoded array of tag names to filter by, e.g. `["enterprise","priority"]`. '
                    "Returns accounts that have any of the listed tags. "
                    "Malformed values (not a JSON-encoded list of strings) return a 400."
                ),
            ),
            OpenApiParameter(
                name="csm",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description=("Filter by CSM. Use 'unassigned' for accounts with no CSM, or an integer user id."),
            ),
            OpenApiParameter(
                name="account_executive",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by account executive. Use 'unassigned' or an integer user id.",
            ),
            OpenApiParameter(
                name="account_owner",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by account owner. Use 'unassigned' or an integer user id.",
            ),
            OpenApiParameter(
                name="all_roles_unassigned",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "When true, returns only accounts where CSM, account executive, and account owner are all unset."
                ),
            ),
            OpenApiParameter(
                name="ordering",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["name", "-name", "created_at", "-created_at", "updated_at", "-updated_at"],
                description="Sort order. Defaults to '-created_at'.",
            ),
        ],
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        tags = _parse_tags_param(self.request)
        ordering = request.query_params.get("ordering")
        ordering = ordering if ordering in self.ALLOWED_ORDERING else None
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_accounts_for_view(
                team_id=self.team_id,
                user_access_control=self.user_access_control,
                offset=offset,
                limit=limit,
                search=request.query_params.get("search", "").strip() or None,
                tags=tags,
                csm=request.query_params.get("csm"),
                account_executive=request.query_params.get("account_executive"),
                account_owner=request.query_params.get("account_owner"),
                all_roles_unassigned=request.query_params.get("all_roles_unassigned", "").lower() == "true",
                ordering=ordering,
            ),
            AccountSerializer,
        )

    @extend_schema(parameters=[_ACCOUNT_ID_PARAM])
    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        try:
            account = api.get_account_for_view(
                team_id=self.team_id,
                account_id=self.kwargs["pk"],
                user_access_control=self.user_access_control,
                required_level=_object_required_level(request, write=False),
            )
        except api.Account_DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except api.ResourceForbiddenError:
            raise PermissionDenied()
        return Response(AccountSerializer(instance=account).data)

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = AccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            account = api.create_account_for_view(
                team_id=self.team_id,
                team=self.team,
                input=contracts.CreateAccountInput(
                    name=data.name,
                    external_id=data.external_id,
                    properties=data.properties or {},
                    tags=_account_tags_input(serializer),
                ),
                organization_id=self.organization.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
            )
        except api.AccountPropertiesValidationError as e:
            raise ValidationError({"properties": e.messages})
        except api.AccountConflictError as e:
            raise Conflict(str(e))
        return Response(AccountSerializer(instance=account).data, status=status.HTTP_201_CREATED)

    @extend_schema(parameters=[_ACCOUNT_ID_PARAM])
    def update(self, request: Request, *args, **kwargs) -> Response:
        partial = kwargs.pop("partial", False)
        serializer = AccountSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            account = api.update_account_for_view(
                team_id=self.team_id,
                account_id=self.kwargs["pk"],
                input=contracts.UpdateAccountInput(
                    name=data.name if "name" in request.data else None,
                    external_id=data.external_id if "external_id" in request.data else None,
                    external_id_provided="external_id" in request.data,
                    properties=data.properties if "properties" in request.data else None,
                    properties_provided="properties" in request.data,
                    tags=_account_tags_input(serializer),
                ),
                user_access_control=self.user_access_control,
                required_level=_object_required_level(request, write=True),
                organization_id=self.organization.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
            )
        except api.Account_DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except api.ResourceForbiddenError:
            raise PermissionDenied()
        except api.AccountPropertiesValidationError as e:
            raise ValidationError({"properties": e.messages})
        except api.AccountConflictError as e:
            raise Conflict(str(e))
        return Response(AccountSerializer(instance=account).data)

    @extend_schema(parameters=[_ACCOUNT_ID_PARAM])
    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    @extend_schema(parameters=[_ACCOUNT_ID_PARAM])
    def destroy(self, request: Request, *args, **kwargs) -> Response:
        try:
            api.delete_account_for_view(
                team_id=self.team_id,
                account_id=self.kwargs["pk"],
                user_access_control=self.user_access_control,
                required_level=_object_required_level(request, write=True),
                organization_id=self.organization.id,
                user=cast(User, request.user),
                was_impersonated=is_impersonated(request),
            )
        except api.Account_DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except api.ResourceForbiddenError:
            raise PermissionDenied()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _account_tags_input(serializer) -> list[str] | None:
    """Tags exactly as the client supplied them (raw initial data), so ``None`` (omitted)
    is distinguished from ``[]`` (clear) — matching ``TaggedItemSerializerMixin``."""
    return serializer.initial_data.get("tags")


@extend_schema(
    tags=["customer_analytics"],
    parameters=[
        OpenApiParameter(
            name="account_id",
            type=OpenApiTypes.UUID,
            location=OpenApiParameter.PATH,
            description="UUID of the parent account.",
        ),
    ],
)
class AccountNotebookViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "account"
    serializer_class = AccountNotebookSerializer
    queryset = None
    lookup_field = "short_id"

    ALLOWED_ORDERING = frozenset({"created_at", "-created_at", "created_by", "-created_by"})

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="search",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Full-text search across notebook title and content.",
            ),
            OpenApiParameter(
                name="ordering",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["created_at", "-created_at", "created_by", "-created_by"],
                description="Sort by creation date or author. Defaults to '-created_at'.",
            ),
        ],
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        ordering = request.query_params.get("ordering")
        ordering = ordering if ordering in self.ALLOWED_ORDERING else None
        notebooks = api.list_account_notebooks(
            self.team_id,
            self.parents_query_dict["account_id"],
            user_access_control=self.user_access_control,
            search=request.query_params.get("search", "").strip() or None,
            order=ordering,
        )
        if notebooks is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        page = self.paginate_queryset(notebooks)
        if page is not None:
            return self.get_paginated_response(AccountNotebookSerializer(instance=page, many=True).data)
        return Response(AccountNotebookSerializer(instance=notebooks, many=True).data)

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        notebook = api.get_account_notebook(
            self.team_id,
            self.parents_query_dict["account_id"],
            self.kwargs["short_id"],
            user_access_control=self.user_access_control,
        )
        if notebook is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AccountNotebookSerializer(instance=notebook).data)

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = AccountNotebookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        notebook = api.create_account_notebook(
            team_id=self.team_id,
            team=self.team,
            account_id=self.parents_query_dict["account_id"],
            input=contracts.CreateAccountNotebookInput(
                title=data.title,
                content=data.content,
                text_content=data.text_content,
                synthesized_content=_synthesize_notebook_content(data.text_content, data.content),
            ),
            user=cast(User, request.user),
            user_access_control=self.user_access_control,
        )
        if notebook is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AccountNotebookSerializer(instance=notebook).data, status=status.HTTP_201_CREATED)

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        deleted = api.delete_account_notebook(
            team_id=self.team_id,
            account_id=self.parents_query_dict["account_id"],
            short_id=self.kwargs["short_id"],
            user_access_control=self.user_access_control,
        )
        if not deleted:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _synthesize_notebook_content(text_content, existing_content):
    """When the caller passed Markdown ``text_content`` but no usable ProseMirror ``content``
    tree, build one from the Markdown. Agents calling the MCP notebook-create tool typically
    send ``text_content`` only (hand-writing ProseMirror is awkward), and NotebookScene only
    renders ``content`` — so without this the result is a blank page. The tiptap helper lives
    in ``ee.hogai`` and stays in the view so it never reaches the facade import path. Returns
    ``None`` when the caller already supplied usable content (or no markdown)."""
    has_usable_content = (
        isinstance(existing_content, dict)
        and existing_content.get("type") == "doc"
        and isinstance(existing_content.get("content"), list)
    )
    if text_content and not has_usable_content:
        return {"type": "doc", "content": markdown_to_tiptap_nodes(text_content) or [{"type": "paragraph"}]}
    return None


# Module-level (not ViewSet static methods) so the ``list[int]`` return annotation resolves to
# the builtin: the ViewSets define a ``list`` method that shadows ``list`` inside the class body.
def _parse_int_ids_param(request: Request, name: str) -> list[int]:
    """Parse a repeated or comma-joined integer-id query param (e.g. ``created_by`` / ``assigned_to``).

    The generated client serializes an array as a single comma-joined value; accept that
    and the repeated-param form alike."""
    ids: list[int] = []
    for value in request.query_params.getlist(name):
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            if not part.isdigit():
                raise ValidationError({name: "Must be a comma-separated list of numeric user IDs."})
            ids.append(int(part))
    return ids


def _parse_uuid_param(request: Request, name: str) -> UUID | None:
    if raw := request.query_params.get(name):
        try:
            return UUID(raw)
        except ValueError:
            raise ValidationError({name: "Must be a valid UUID."})
    return None


@extend_schema(tags=["customer_analytics"])
class AccountNotesViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    _FacadePaginationMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "account"
    serializer_class = AccountNoteSerializer
    queryset = None  # data is reached through the facade; declared for router/schema only

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="search",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Full-text search across note title and content, plus substring match on account name.",
            ),
            OpenApiParameter(
                name="account_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Only return notes linked to this account.",
            ),
            OpenApiParameter(
                name="created_by",
                type=OpenApiTypes.INT,
                many=True,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Only return notes created by these user IDs (repeat the param per user).",
            ),
            OpenApiParameter(
                name="assigned_to",
                type=OpenApiTypes.INT,
                many=True,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Only return notes on accounts assigned to these user IDs "
                "(the account's CSM or account executive; repeat the param per user).",
            ),
        ],
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_account_notes_for_view(
                team_id=self.team_id,
                user_access_control=self.user_access_control,
                offset=offset,
                limit=limit,
                search=request.query_params.get("search", "").strip() or None,
                account_id=_parse_uuid_param(request, "account_id"),
                created_by_ids=_parse_int_ids_param(request, "created_by") or None,
                assigned_to_ids=_parse_int_ids_param(request, "assigned_to") or None,
            ),
            AccountNoteSerializer,
        )


@extend_schema(
    tags=["customer_analytics"],
    parameters=[
        OpenApiParameter(
            name="account_id",
            type=OpenApiTypes.UUID,
            location=OpenApiParameter.PATH,
            description="UUID of the parent account.",
        ),
    ],
)
class CustomPropertyValueViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.GenericViewSet):
    scope_object = "account"
    serializer_class = CustomPropertyValueSerializer
    pagination_class = None

    def _accessible_account_id(self) -> str | None:
        """The parent account's id when the caller has object-level access to it, else ``None``
        (mapped to 404). Object-access filtering lives behind the facade — the view imports no models."""
        return api.get_accessible_account_id(
            self.team_id, self.parents_query_dict["account_id"], user_access_control=self.user_access_control
        )

    @extend_schema(responses={200: CustomPropertyValueSerializer(many=True)})
    def list(self, request: Request, *args, **kwargs) -> Response:
        account_id = self._accessible_account_id()
        if account_id is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        values = api.list_active_custom_property_values(self.team_id, account_id)
        return Response(CustomPropertyValueSerializer(values, many=True).data)

    @extend_schema(request=CustomPropertyValueWriteSerializer, responses={201: CustomPropertyValueSerializer})
    def create(self, request: Request, *args, **kwargs) -> Response:
        account_id = self._accessible_account_id()
        if account_id is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        write = CustomPropertyValueWriteSerializer(data=request.data)
        write.is_valid(raise_exception=True)

        try:
            value = api.set_custom_property_value(
                team_id=self.team_id,
                account_id=account_id,
                definition_id=write.validated_data["definition"],
                value=write.validated_data["value"],
                created_by_id=request.user.id,
            )
        except api.Account_DoesNotExist:
            # The account passed the access pre-check but was deleted before the write committed.
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except api.CustomPropertyDefinitionNotFound:
            raise ValidationError({"definition": "Custom property definition not found."})
        except api.CustomPropertyValueSourceManaged as exc:
            raise ValidationError({"definition": str(exc)})
        except api.InvalidCustomPropertyValue as exc:
            raise ValidationError({"value": str(exc)})
        except api.CustomPropertyValueConflict as exc:
            raise Conflict(str(exc))

        return Response(CustomPropertyValueSerializer(value).data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["customer_analytics"],
    parameters=[
        OpenApiParameter(
            name="account_id",
            type=OpenApiTypes.UUID,
            location=OpenApiParameter.PATH,
            description="UUID of the parent account.",
        ),
    ],
)
class AccountRelationshipViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.GenericViewSet):
    scope_object = "account"
    serializer_class = AccountRelationshipSerializer
    pagination_class = None

    def _accessible_account_id(self) -> str | None:
        """The parent account's id when the caller has object-level access to it, else ``None``
        (mapped to 404). Object-access filtering lives behind the facade — the view imports no models."""
        return api.get_accessible_account_id(
            self.team_id, self.parents_query_dict["account_id"], user_access_control=self.user_access_control
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "include_history",
                OpenApiTypes.BOOL,
                description="Include ended assignments (the full timeline), not just active ones.",
            )
        ],
        responses={200: AccountRelationshipSerializer(many=True)},
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        account_id = self._accessible_account_id()
        if account_id is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        relationships = api.list_account_relationships(
            team_id=self.team_id,
            account_id=account_id,
            include_history=request.query_params.get("include_history", "").lower() == "true",
        )
        return Response(AccountRelationshipSerializer(relationships, many=True).data)

    @extend_schema(request=AccountRelationshipWriteSerializer, responses={201: AccountRelationshipSerializer})
    def create(self, request: Request, *args, **kwargs) -> Response:
        account_id = self._accessible_account_id()
        if account_id is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        write = AccountRelationshipWriteSerializer(data=request.data)
        write.is_valid(raise_exception=True)
        try:
            relationship = api.assign_account_relationship(
                team_id=self.team_id,
                account_id=account_id,
                definition_id=write.validated_data["definition"],
                user_id=write.validated_data["user"],
                created_by=cast(User, request.user),
            )
        except api.Account_DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        except api.AccountRelationshipDefinitionNotFound:
            raise ValidationError({"definition": "Relationship definition not found."})
        except api.AccountRelationshipAssigneeNotInOrganization:
            raise ValidationError({"user": "User is not a member of this organization."})
        return Response(AccountRelationshipSerializer(relationship).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: AccountRelationshipSerializer})
    @action(methods=["POST"], detail=True)
    def end(self, request: Request, *args, **kwargs) -> Response:
        account_id = self._accessible_account_id()
        if account_id is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        relationship = api.end_account_relationship(
            team_id=self.team_id, account_id=account_id, relationship_id=self.kwargs["pk"]
        )
        if relationship is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AccountRelationshipSerializer(relationship).data)
_EVENT_STREAM_ID_PARAM = OpenApiParameter(
    "id",
    OpenApiTypes.STR,
    OpenApiParameter.PATH,
    description="A UUID string identifying this event stream.",
)


@extend_schema(tags=["customer_analytics"])
class EventStreamViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    _FacadePaginationMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """The team's event stream: a live feed of selected accounts' events posted to a Slack
    channel. Delivery runs through a managed CDP destination that is re-provisioned inside
    the same transaction as every write, so config and delivery can't drift apart."""

    scope_object = "account"
    serializer_class = EventStreamSerializer
    queryset = None  # data is reached through the facade; declared for router/schema only

    def list(self, request: Request, *args, **kwargs) -> Response:
        return self._paginate_via_facade(
            request,
            lambda offset, limit: api.list_event_streams(self.team_id, offset=offset, limit=limit),
            EventStreamSerializer,
        )

    @extend_schema(parameters=[_EVENT_STREAM_ID_PARAM])
    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        stream = api.get_event_stream(self.team_id, self.kwargs["pk"])
        if stream is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(EventStreamSerializer(instance=stream).data)

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = EventStreamSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = cast(User, request.user)
        try:
            with transaction.atomic():
                stream = api.create_event_stream(
                    team_id=self.team_id,
                    enabled=data.enabled,
                    event_names=data.event_names,
                    slack_integration_id=data.slack_integration,
                    slack_channel_id=data.slack_channel_id,
                    slack_channel_name=data.slack_channel_name,
                    user=user,
                )
                event_stream_destination.sync_event_stream_destination_by_id(
                    team=self.team, stream_id=str(stream.id), user=user
                )
        except api.EventStreamValidationError as e:
            raise ValidationError(str(e))
        except api.EventStreamConflictError as e:
            raise Conflict(str(e))
        return Response(
            EventStreamSerializer(instance=api.get_event_stream(self.team_id, str(stream.id))).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(parameters=[_EVENT_STREAM_ID_PARAM])
    def update(self, request: Request, *args, **kwargs) -> Response:
        partial = kwargs.pop("partial", False)
        serializer = EventStreamSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        user = cast(User, request.user)
        try:
            with transaction.atomic():
                stream = api.update_event_stream(
                    team_id=self.team_id,
                    stream_id=self.kwargs["pk"],
                    fields=_event_stream_write_fields(serializer.validated_data, request.data),
                )
                if stream is None:
                    return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
                event_stream_destination.sync_event_stream_destination_by_id(
                    team=self.team, stream_id=str(stream.id), user=user
                )
        except api.EventStreamValidationError as e:
            raise ValidationError(str(e))
        return Response(EventStreamSerializer(instance=api.get_event_stream(self.team_id, str(stream.id))).data)

    @extend_schema(parameters=[_EVENT_STREAM_ID_PARAM])
    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    @extend_schema(parameters=[_EVENT_STREAM_ID_PARAM])
    def destroy(self, request: Request, *args, **kwargs) -> Response:
        with transaction.atomic():
            event_stream_destination.archive_event_stream_destination_by_id(
                team_id=self.team_id, stream_id=self.kwargs["pk"]
            )
            deleted = api.delete_event_stream(team_id=self.team_id, stream_id=self.kwargs["pk"])
        if not deleted:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        parameters=[_EVENT_STREAM_ID_PARAM],
        request=EventStreamMemberWriteSerializer,
        responses={200: EventStreamSerializer},
    )
    @action(methods=["POST"], detail=True)
    def add_account(self, request: Request, *args, **kwargs) -> Response:
        return self._set_member(request, included=True)

    @extend_schema(
        parameters=[_EVENT_STREAM_ID_PARAM],
        request=EventStreamMemberWriteSerializer,
        responses={200: EventStreamSerializer},
    )
    @action(methods=["POST"], detail=True)
    def remove_account(self, request: Request, *args, **kwargs) -> Response:
        return self._set_member(request, included=False)

    def _set_member(self, request: Request, *, included: bool) -> Response:
        write = EventStreamMemberWriteSerializer(data=request.data)
        write.is_valid(raise_exception=True)
        user = cast(User, request.user)
        try:
            with transaction.atomic():
                stream = api.set_event_stream_member(
                    team_id=self.team_id,
                    stream_id=self.kwargs["pk"],
                    account_id=write.validated_data["account_id"],
                    included=included,
                    user=user,
                )
                if stream is None:
                    return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
                event_stream_destination.sync_event_stream_destination_by_id(
                    team=self.team, stream_id=str(stream.id), user=user
                )
        except api.Account_DoesNotExist:
            raise ValidationError({"account_id": "Account not found for this team."})
        return Response(EventStreamSerializer(instance=stream).data)


def _event_stream_write_fields(validated, raw_data: dict) -> dict:
    """The event-stream columns the caller actually sent, so a PATCH that omits a field
    leaves it untouched (the serializer fields carry defaults for create)."""
    fields: dict = {}
    if "enabled" in raw_data:
        fields["enabled"] = validated.enabled
    if "event_names" in raw_data:
        fields["event_names"] = validated.event_names
    if "slack_integration" in raw_data:
        fields["slack_integration_id"] = validated.slack_integration
    if "slack_channel_id" in raw_data:
        fields["slack_channel_id"] = validated.slack_channel_id
    if "slack_channel_name" in raw_data:
        fields["slack_channel_name"] = validated.slack_channel_name
    return fields
