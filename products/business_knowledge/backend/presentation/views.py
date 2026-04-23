"""
DRF views for business_knowledge.

Thin shell: validate input, call the facade, serialize DTOs back out.
All team-scoping goes through `safely_get_queryset` and the facade accepts
team_id explicitly so it's impossible to accidentally leak across teams.
"""

from typing import cast
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.permissions import APIScopePermission

from ..facade import api, contracts
from ..logic import (
    EmptyContentError,
    InvalidUrlError,
    QuotaExceededError,
    SourceBusyError,
    TextTooLargeError,
    UrlFetchFailedError,
)
from ..models import KnowledgeSource
from .serializers import (
    CreateTextSourceSerializer,
    CreateUrlSourceSerializer,
    KnowledgeSourceSerializer,
    UpdateTextSourceSerializer,
)


class _ConflictError(exceptions.APIException):
    # 409 is the right semantics for "resource is currently busy / in a
    # state that conflicts with the request". DRF has no first-class helper
    # for it, hence the tiny subclass.
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Resource is busy."
    default_code = "conflict"


@extend_schema(tags=["business_knowledge"])
class KnowledgeSourceViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "business_knowledge"
    queryset = KnowledgeSource.objects.all()
    serializer_class = KnowledgeSourceSerializer
    permission_classes = [IsAuthenticated, APIScopePermission]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        # TeamAndOrgViewSetMixin already filters via _filter_queryset_by_parents_lookups
        # (team_id kwarg), but we re-apply for defense-in-depth — if routing
        # ever regresses, queryset stays team-bound.
        return queryset.filter(team_id=self.team_id)

    @extend_schema(responses={200: KnowledgeSourceSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        sources = api.list_for_team(self.team_id)
        page = self.paginate_queryset(sources)
        if page is not None:
            return self.get_paginated_response(KnowledgeSourceSerializer(instance=page, many=True).data)
        return Response(KnowledgeSourceSerializer(instance=sources, many=True).data)

    @extend_schema(
        request=CreateTextSourceSerializer,
        responses={201: KnowledgeSourceSerializer},
    )
    def create(self, request: Request, **kwargs) -> Response:
        # Dispatch on `source_type` — a single endpoint keeps the URL shape
        # simple for the SDK / MCP. Defaulting to "text" preserves the Stage 1
        # contract when the client omits the field.
        source_type = request.data.get("source_type", "text")
        if source_type == "url":
            return self._create_url_source(request)
        return self._create_text_source(request)

    def _create_text_source(self, request: Request) -> Response:
        serializer = CreateTextSourceSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        user = cast(User, request.user)
        try:
            dto = api.create_text_source(
                contracts.CreateTextSourceInput(
                    team_id=self.team_id,
                    created_by_id=getattr(user, "id", None),
                    name=serializer.validated_data["name"],
                    text=serializer.validated_data["text"],
                )
            )
        except TextTooLargeError:
            raise exceptions.ValidationError({"text": "Text exceeds the maximum allowed size."})
        except QuotaExceededError:
            # 402 is reserved for billing; using 429 to surface "slow down"
            # semantics to the UI so it can nudge the user to delete sources.
            raise exceptions.Throttled(detail="Knowledge source quota exceeded for this project.")
        return Response(KnowledgeSourceSerializer(instance=dto).data, status=status.HTTP_201_CREATED)

    def _create_url_source(self, request: Request) -> Response:
        serializer = CreateUrlSourceSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        user = cast(User, request.user)
        try:
            dto = api.create_url_source(
                contracts.CreateUrlSourceInput(
                    team_id=self.team_id,
                    created_by_id=getattr(user, "id", None),
                    name=serializer.validated_data["name"],
                    url=serializer.validated_data["url"],
                )
            )
        except InvalidUrlError:
            raise exceptions.ValidationError({"url": "URL is not reachable."})
        except (UrlFetchFailedError, EmptyContentError):
            raise exceptions.ValidationError({"url": "Could not fetch the URL."})
        except QuotaExceededError:
            raise exceptions.Throttled(detail="Knowledge source quota exceeded for this project.")
        return Response(KnowledgeSourceSerializer(instance=dto).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: KnowledgeSourceSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs) -> Response:
        try:
            source_id = UUID(pk)
        except (ValueError, DjangoValidationError):
            raise exceptions.NotFound()
        dto = api.get_for_team(source_id, self.team_id)
        if dto is None:
            raise exceptions.NotFound()
        return Response(KnowledgeSourceSerializer(instance=dto).data)

    @extend_schema(
        request=UpdateTextSourceSerializer,
        responses={200: KnowledgeSourceSerializer},
    )
    def partial_update(self, request: Request, pk: str, **kwargs) -> Response:
        try:
            source_id = UUID(pk)
        except (ValueError, DjangoValidationError):
            raise exceptions.NotFound()
        serializer = UpdateTextSourceSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        try:
            dto = api.update_text_source(
                contracts.UpdateTextSourceInput(
                    source_id=source_id,
                    team_id=self.team_id,
                    name=serializer.validated_data.get("name"),
                    text=serializer.validated_data.get("text"),
                )
            )
        except TextTooLargeError:
            raise exceptions.ValidationError({"text": "Text exceeds the maximum allowed size."})
        except QuotaExceededError:
            raise exceptions.Throttled(detail="Knowledge source quota exceeded for this project.")
        if dto is None:
            raise exceptions.NotFound()
        return Response(KnowledgeSourceSerializer(instance=dto).data)

    @extend_schema(responses={200: {"type": "object", "properties": {"text": {"type": "string"}}}})
    @action(detail=True, methods=["get"], url_path="text")
    def text(self, request: Request, pk: str, **kwargs) -> Response:
        try:
            source_id = UUID(pk)
        except (ValueError, DjangoValidationError):
            raise exceptions.NotFound()
        content = api.get_source_text(source_id, self.team_id)
        if content is None:
            raise exceptions.NotFound()
        return Response({"text": content})

    @extend_schema(responses={200: KnowledgeSourceSerializer})
    @action(detail=True, methods=["post"], url_path="refresh")
    def refresh(self, request: Request, pk: str, **kwargs) -> Response:
        try:
            source_id = UUID(pk)
        except (ValueError, DjangoValidationError):
            raise exceptions.NotFound()
        try:
            dto = api.refresh_source(source_id, self.team_id)
        except SourceBusyError:
            raise _ConflictError("A refresh is already in progress for this source.")
        except InvalidUrlError:
            raise exceptions.ValidationError({"url": "URL is not reachable."})
        except (UrlFetchFailedError, EmptyContentError):
            # We still persisted the ERROR state inside logic.refresh_source,
            # so refetching the source will show the latest failure to the user.
            raise exceptions.ValidationError({"url": "Could not fetch the URL."})
        if dto is None:
            raise exceptions.NotFound()
        return Response(KnowledgeSourceSerializer(instance=dto).data)

    @extend_schema(responses={204: None})
    def destroy(self, request: Request, pk: str, **kwargs) -> Response:
        try:
            source_id = UUID(pk)
        except (ValueError, DjangoValidationError):
            raise exceptions.NotFound()
        # Route the delete through the ORM so ModelActivityMixin fires (the
        # facade helper does a QuerySet.delete() which bypasses save signals
        # but the mixin hooks delete specifically).
        try:
            source = KnowledgeSource.objects.get(id=source_id, team_id=self.team_id)
        except KnowledgeSource.DoesNotExist:
            raise exceptions.NotFound()
        source.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
