"""DRF views for business_knowledge."""

from typing import cast
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission
from posthog.rate_limit import BurstRateThrottle, SustainedRateThrottle

from .. import logic
from ..file_parse import FileParseError
from ..models import KnowledgeSource, SourceType
from ..models.constants import CrawlMode
from .serializers import (
    CreateCrawlSourceSerializer,
    CreateFileSourceSerializer,
    CreateTextSourceSerializer,
    CreateUrlSourceSerializer,
    KnowledgeSourceSerializer,
    UpdateTextSourceSerializer,
    UpdateUrlSourceSerializer,
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
    queryset = KnowledgeSource.objects.unscoped()
    serializer_class = KnowledgeSourceSerializer
    permission_classes = [IsAuthenticated, APIScopePermission, PostHogFeatureFlagPermission]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    posthog_feature_flag = "product-business-knowledge"
    throttle_classes = [BurstRateThrottle, SustainedRateThrottle]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team_id=self.team_id)

    @extend_schema(responses={200: KnowledgeSourceSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        sources = logic.list_for_team(self.team_id)
        page = self.paginate_queryset(sources)
        if page is not None:
            return self.get_paginated_response(KnowledgeSourceSerializer(instance=page, many=True).data)
        return Response(KnowledgeSourceSerializer(instance=sources, many=True).data)

    @extend_schema(
        request=CreateTextSourceSerializer,
        responses={201: KnowledgeSourceSerializer},
    )
    def create(self, request: Request, **kwargs) -> Response:
        source_type = request.data.get("source_type", SourceType.TEXT.value)
        if source_type == SourceType.FILE.value:
            return self._create_file_source(request)
        if source_type == SourceType.URL.value:
            crawl_mode = request.data.get("crawl_mode")
            if crawl_mode and crawl_mode != CrawlMode.SINGLE.value:
                return self._create_crawl_source(request)
            return self._create_url_source(request)
        return self._create_text_source(request)

    def _create_text_source(self, request: Request) -> Response:
        serializer = CreateTextSourceSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        user = cast(User, request.user)
        try:
            source = logic.create_text_source(
                team_id=self.team_id,
                created_by_id=user.id,
                name=serializer.validated_data["name"],
                text=serializer.validated_data["text"],
            )
        except logic.TextTooLargeError:
            raise exceptions.ValidationError({"text": "Text exceeds the maximum allowed size."})
        except logic.QuotaExceededError:
            raise exceptions.PermissionDenied(detail="Knowledge source quota exceeded for this project.")
        return Response(KnowledgeSourceSerializer(instance=source).data, status=status.HTTP_201_CREATED)

    def _create_url_source(self, request: Request) -> Response:
        serializer = CreateUrlSourceSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        user = cast(User, request.user)
        try:
            source = logic.create_url_source(
                team_id=self.team_id,
                created_by_id=user.id,
                name=serializer.validated_data["name"],
                url=serializer.validated_data["url"],
            )
        except logic.SourceBusyError:
            raise _ConflictError("Another source is already being processed. Please wait and try again.")
        except logic.InvalidUrlError:
            raise exceptions.ValidationError({"url": "URL is not reachable."})
        except (logic.UrlFetchFailedError, logic.EmptyContentError):
            raise exceptions.ValidationError({"url": "Could not fetch the URL."})
        except logic.QuotaExceededError:
            raise exceptions.PermissionDenied(detail="Knowledge source quota exceeded for this project.")
        return Response(KnowledgeSourceSerializer(instance=source).data, status=status.HTTP_201_CREATED)

    def _create_crawl_source(self, request: Request) -> Response:
        serializer = CreateCrawlSourceSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        user = cast(User, request.user)
        try:
            source = logic.create_crawl_source(
                team_id=self.team_id,
                created_by_id=user.id,
                name=serializer.validated_data["name"],
                url=serializer.validated_data["url"],
                crawl_mode=serializer.validated_data["crawl_mode"],
                crawl_config=serializer.validated_data["crawl_config"],
            )
        except logic.SourceBusyError:
            raise _ConflictError("Another source is already being processed. Please wait and try again.")
        except logic.InvalidUrlError:
            raise exceptions.ValidationError({"url": "URL is not reachable."})
        except (logic.UrlFetchFailedError, logic.EmptyContentError):
            raise exceptions.ValidationError({"url": "Crawl failed — could not fetch any pages."})
        except logic.QuotaExceededError:
            raise exceptions.PermissionDenied(detail="Knowledge source quota exceeded for this project.")
        return Response(KnowledgeSourceSerializer(instance=source).data, status=status.HTTP_201_CREATED)

    def _create_file_source(self, request: Request) -> Response:
        serializer = CreateFileSourceSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        user = cast(User, request.user)

        uploaded = serializer.validated_data["file"]
        file_data = uploaded.read()

        try:
            source = logic.create_file_source(
                team_id=self.team_id,
                created_by_id=user.id,
                name=serializer.validated_data["name"],
                file_data=file_data,
                original_filename=uploaded.name or "unnamed",
            )
        except FileParseError as exc:
            raise exceptions.ValidationError({"file": str(exc) or "Unable to parse the uploaded file."})
        except logic.QuotaExceededError:
            raise exceptions.PermissionDenied(detail="Knowledge source quota exceeded for this project.")
        return Response(KnowledgeSourceSerializer(instance=source).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: KnowledgeSourceSerializer})
    def retrieve(self, request: Request, pk: str, **kwargs) -> Response:
        try:
            source_id = UUID(pk)
        except (ValueError, DjangoValidationError):
            raise exceptions.NotFound()
        source = logic.get_for_team(source_id, self.team_id)
        if source is None:
            raise exceptions.NotFound()
        return Response(KnowledgeSourceSerializer(instance=source).data)

    @extend_schema(
        request=UpdateTextSourceSerializer,
        responses={200: KnowledgeSourceSerializer},
    )
    def partial_update(self, request: Request, pk: str, **kwargs) -> Response:
        try:
            source_id = UUID(pk)
        except (ValueError, DjangoValidationError):
            raise exceptions.NotFound()

        try:
            source = KnowledgeSource.objects.get(id=source_id, team_id=self.team_id)
        except KnowledgeSource.DoesNotExist:
            raise exceptions.NotFound()

        if source.source_type == SourceType.URL.value:
            return self._update_url_source(source, request)
        if source.source_type == SourceType.FILE.value:
            return self._update_file_source(source, request)
        return self._update_text_or_file_source(source, request)

    def _update_file_source(self, source: KnowledgeSource, request: Request) -> Response:
        """FILE sources only allow name changes — content comes from the original upload."""
        serializer = UpdateTextSourceSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        if "text" in serializer.validated_data:
            raise exceptions.ValidationError(
                {"text": "File sources cannot have their text replaced. Re-upload instead."}
            )
        try:
            updated = logic.update_text_source(
                source_id=source.id,
                team_id=self.team_id,
                name=serializer.validated_data.get("name"),
                text=None,
            )
        except logic.QuotaExceededError:
            raise exceptions.PermissionDenied(detail="Knowledge source quota exceeded for this project.")
        if updated is None:
            raise exceptions.NotFound()
        return Response(KnowledgeSourceSerializer(instance=updated).data)

    def _update_text_or_file_source(self, source: KnowledgeSource, request: Request) -> Response:
        serializer = UpdateTextSourceSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        try:
            updated = logic.update_text_source(
                source_id=source.id,
                team_id=self.team_id,
                name=serializer.validated_data.get("name"),
                text=serializer.validated_data.get("text"),
            )
        except logic.TextTooLargeError:
            raise exceptions.ValidationError({"text": "Text exceeds the maximum allowed size."})
        except logic.QuotaExceededError:
            raise exceptions.PermissionDenied(detail="Knowledge source quota exceeded for this project.")
        if updated is None:
            raise exceptions.NotFound()
        return Response(KnowledgeSourceSerializer(instance=updated).data)

    def _update_url_source(self, source: KnowledgeSource, request: Request) -> Response:
        serializer = UpdateUrlSourceSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        try:
            updated = logic.update_url_source(
                source_id=source.id,
                team_id=self.team_id,
                name=serializer.validated_data.get("name"),
                url=serializer.validated_data.get("url"),
                crawl_mode=serializer.validated_data.get("crawl_mode"),
                crawl_config=serializer.validated_data.get("crawl_config"),
            )
        except logic.InvalidUrlError:
            raise exceptions.ValidationError({"url": "URL is not reachable."})
        except (logic.UrlFetchFailedError, logic.EmptyContentError):
            raise exceptions.ValidationError({"url": "Could not fetch the URL."})
        except logic.SourceBusyError:
            raise _ConflictError("A refresh is already in progress for this source.")
        except logic.QuotaExceededError:
            raise exceptions.PermissionDenied(detail="Knowledge source quota exceeded for this project.")
        if updated is None:
            raise exceptions.NotFound()
        return Response(KnowledgeSourceSerializer(instance=updated).data)

    @extend_schema(responses={200: {"type": "object", "properties": {"text": {"type": "string"}}}})
    @action(detail=True, methods=["get"], url_path="text")
    def text(self, request: Request, pk: str, **kwargs) -> Response:
        try:
            source_id = UUID(pk)
        except (ValueError, DjangoValidationError):
            raise exceptions.NotFound()
        content = logic.get_source_text_for_team(source_id, self.team_id)
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
            source = logic.refresh_source(source_id=source_id, team_id=self.team_id)
        except logic.SourceBusyError:
            raise _ConflictError("A refresh is already in progress for this source.")
        except logic.InvalidUrlError:
            raise exceptions.ValidationError({"url": "URL is not reachable."})
        except (logic.UrlFetchFailedError, logic.EmptyContentError):
            raise exceptions.ValidationError({"url": "Could not fetch the URL."})
        except logic.QuotaExceededError:
            raise exceptions.PermissionDenied(detail="Knowledge source quota exceeded for this project.")
        if source is None:
            raise exceptions.NotFound()
        return Response(KnowledgeSourceSerializer(instance=source).data)

    @extend_schema(responses={204: None})
    def destroy(self, request: Request, pk: str, **kwargs) -> Response:
        try:
            source_id = UUID(pk)
        except (ValueError, DjangoValidationError):
            raise exceptions.NotFound()
        if not logic.delete_source(source_id, self.team_id):
            raise exceptions.NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)
