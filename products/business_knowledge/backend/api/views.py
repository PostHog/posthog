"""DRF views for business_knowledge."""

from typing import Any, cast
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet

import structlog
from asgiref.sync import async_to_sync
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
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
from posthog.temporal.common.client import sync_connect

from .. import logic
from ..constants import BK_DRILLDOWN_DEFAULT_RADIUS, BK_DRILLDOWN_MAX_RADIUS
from ..file_parse import FileParseError
from ..models import GapStatus, KnowledgeDocument, KnowledgeGapSuggestion, KnowledgeSource, SourceType
from ..models.constants import CrawlMode
from ..temporal.coordinator import IngestSourceInputs, RefreshSourceInputs
from .serializers import (
    AggregatedGapSerializer,
    CreateCrawlSourceSerializer,
    CreateFileSourceSerializer,
    CreateTextSourceSerializer,
    CreateUrlSourceSerializer,
    GapActionSerializer,
    GapTopicActionResultSerializer,
    GapTopicActionSerializer,
    KnowledgeDocumentWindowSerializer,
    KnowledgeGapSuggestionSerializer,
    KnowledgeSearchResultSerializer,
    KnowledgeSourceSerializer,
    UpdateTextSourceSerializer,
    UpdateUrlSourceSerializer,
)

logger = structlog.get_logger(__name__)


class _ConflictError(exceptions.APIException):
    # 409 is the right semantics for "resource is currently busy / in a
    # state that conflicts with the request". DRF has no first-class helper
    # for it, hence the tiny subclass.
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Resource is busy."
    default_code = "conflict"


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
                always_include=serializer.validated_data.get("always_include", False),
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
            source = logic.claim_url_source(
                team_id=self.team_id,
                created_by_id=user.id,
                name=serializer.validated_data["name"],
                url=serializer.validated_data["url"],
                refresh_interval=serializer.validated_data.get("refresh_interval"),
                always_include=serializer.validated_data.get("always_include", False),
            )
        except logic.SourceBusyError:
            raise _ConflictError("Another source is already being processed. Please wait and try again.")
        except logic.InvalidUrlError:
            raise exceptions.ValidationError({"url": "URL is not reachable."})
        except logic.QuotaExceededError:
            raise exceptions.PermissionDenied(detail="Knowledge source quota exceeded for this project.")
        return self._respond_claimed(source)

    def _create_crawl_source(self, request: Request) -> Response:
        serializer = CreateCrawlSourceSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        user = cast(User, request.user)
        try:
            source = logic.claim_url_source(
                team_id=self.team_id,
                created_by_id=user.id,
                name=serializer.validated_data["name"],
                url=serializer.validated_data["url"],
                crawl_mode=serializer.validated_data["crawl_mode"],
                crawl_config=serializer.validated_data["crawl_config"],
                refresh_interval=serializer.validated_data.get("refresh_interval"),
                always_include=serializer.validated_data.get("always_include", False),
            )
        except logic.SourceBusyError:
            raise _ConflictError("Another source is already being processed. Please wait and try again.")
        except logic.InvalidUrlError:
            raise exceptions.ValidationError({"url": "URL is not reachable."})
        except logic.QuotaExceededError:
            raise exceptions.PermissionDenied(detail="Knowledge source quota exceeded for this project.")
        return self._respond_claimed(source)

    def _respond_claimed(self, source: KnowledgeSource) -> Response:
        """
        Kick off background ingestion and return the just-claimed PROCESSING
        source so the UI unblocks immediately and polls for completion.
        """
        self._start_background_ingest(source)
        fresh = logic.get_for_team(source.id, self.team_id) or source
        return Response(KnowledgeSourceSerializer(instance=fresh).data, status=status.HTTP_201_CREATED)

    def _start_background_ingest(self, source: KnowledgeSource) -> None:
        """
        Hand fetch + index to a background Temporal workflow so the request
        returns right away. If the workflow can't be started (e.g. Temporal is
        unreachable) we fall back to ingesting inline so the source never hangs
        in PROCESSING — the stale-claim sweep would otherwise only recover it
        after several minutes.
        """
        try:
            client = sync_connect()
            # mypy can't resolve Temporal's start_workflow overloads for string-named workflows.
            async_to_sync(client.start_workflow)(  # type: ignore[misc]
                "business-knowledge-ingest-source",  # type: ignore[arg-type]
                IngestSourceInputs(team_id=self.team_id, source_id=str(source.id)),  # type: ignore[arg-type]
                id=f"business-knowledge-ingest-{source.id}",
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            )
        except Exception:
            logger.exception("business_knowledge.ingest.workflow_start_failed", source_id=str(source.id))
            logic.ingest_source(source_id=source.id, team_id=self.team_id)

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
                always_include=serializer.validated_data.get("always_include", False),
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
                always_include=serializer.validated_data.get("always_include"),
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
                always_include=serializer.validated_data.get("always_include"),
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
                refresh_interval=serializer.validated_data.get("refresh_interval"),
                always_include=serializer.validated_data.get("always_include"),
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
            source = logic.claim_refresh_source(source_id=source_id, team_id=self.team_id)
        except KnowledgeSource.DoesNotExist:
            raise exceptions.NotFound()
        except logic.SourceBusyError:
            raise _ConflictError("A refresh is already in progress for this source.")
        except logic.InvalidUrlError:
            raise exceptions.ValidationError({"url": "Only URL sources can be refreshed."})
        except logic.QuotaExceededError:
            raise exceptions.PermissionDenied(detail="Knowledge source quota exceeded for this project.")
        self._start_background_refresh(source)
        fresh = logic.get_for_team(source.id, self.team_id) or source
        return Response(KnowledgeSourceSerializer(instance=fresh).data)

    def _start_background_refresh(self, source: KnowledgeSource) -> None:
        """
        Hand fetch + rebuild to a background Temporal workflow so the request
        returns right away. Falls back to inline refresh if Temporal is
        unreachable.
        """
        try:
            client = sync_connect()
            async_to_sync(client.start_workflow)(  # type: ignore[misc]
                "business-knowledge-refresh-source",  # type: ignore[arg-type]
                RefreshSourceInputs(team_id=self.team_id, source_id=str(source.id)),  # type: ignore[arg-type]
                id=f"business-knowledge-refresh-{source.id}",
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            )
        except Exception:
            logger.exception("business_knowledge.refresh.workflow_start_failed", source_id=str(source.id))
            logic.execute_refresh_source(source_id=source.id, team_id=self.team_id)

    @extend_schema(responses={204: None})
    def destroy(self, request: Request, pk: str, **kwargs) -> Response:
        try:
            source_id = UUID(pk)
        except (ValueError, DjangoValidationError):
            raise exceptions.NotFound()
        if not logic.delete_source(source_id, self.team_id):
            raise exceptions.NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)


class KnowledgeDocumentViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    Read-only access to parsed knowledge documents. Exposes hybrid search
    (``search``) and a drill-down window (``window``) so an agent (PHAI or
    MCP) can find and explore business knowledge chunks.
    """

    scope_object = "business_knowledge"
    queryset = KnowledgeDocument.objects.unscoped()
    serializer_class = KnowledgeDocumentWindowSerializer
    permission_classes = [IsAuthenticated, APIScopePermission, PostHogFeatureFlagPermission]
    posthog_feature_flag = "product-business-knowledge"
    throttle_classes = [BurstRateThrottle, SustainedRateThrottle]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team_id=self.team_id)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "around_ordinal",
                OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Zero-based chunk ordinal to center the window on (from a search result).",
            ),
            OpenApiParameter(
                "radius",
                OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    f"Number of chunks before and after the center to include. "
                    f"Defaults to {BK_DRILLDOWN_DEFAULT_RADIUS}, clamped to [0, {BK_DRILLDOWN_MAX_RADIUS}]."
                ),
            ),
        ],
        responses={200: KnowledgeDocumentWindowSerializer(many=True)},
    )
    @action(
        detail=True,
        methods=["get"],
        url_path="window",
        pagination_class=None,
        # Custom actions aren't in APIScopePermission's default read list, so
        # programmatic tokens (personal API key / OAuth — how MCP authenticates)
        # would otherwise be rejected as "does not support personal API key access".
        required_scopes=["business_knowledge:read"],
    )
    def window(self, request: Request, pk: str, **kwargs) -> Response:
        try:
            document_id = UUID(pk)
        except (ValueError, DjangoValidationError):
            raise exceptions.NotFound()

        # 404 for unknown / cross-team docs before touching the chunk window so
        # an attacker can't probe doc existence. `.unscoped()` + explicit
        # team_id filter mirrors the source viewset (the manager needs an
        # explicit team scope otherwise).
        if not KnowledgeDocument.objects.unscoped().filter(id=document_id, team_id=self.team_id).exists():
            raise exceptions.NotFound()

        around_ordinal = self._parse_int_param(request, "around_ordinal", required=True)
        radius = self._parse_int_param(request, "radius", required=False, default=BK_DRILLDOWN_DEFAULT_RADIUS)

        results = logic.get_document_window(self.team_id, document_id, around_ordinal, radius=radius)
        return Response(KnowledgeDocumentWindowSerializer(instance=results, many=True).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "query",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Natural-language search query. Runs hybrid (semantic + full-text) retrieval over all SAFE, READY knowledge chunks in this project.",
            ),
            OpenApiParameter(
                "limit",
                OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum number of ranked chunks to return. Defaults to 10, capped at 20.",
            ),
            OpenApiParameter(
                "rerank",
                OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "When true, rerank search results with a listwise LLM pass for better relevance. "
                    "Defaults to false (RRF order only). Falls back to RRF order on rerank failure."
                ),
            ),
        ],
        responses={200: KnowledgeSearchResultSerializer(many=True)},
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="search",
        pagination_class=None,
        required_scopes=["business_knowledge:read"],
    )
    def search(self, request: Request, **kwargs) -> Response:
        query = request.query_params.get("query")
        if not query or not query.strip():
            raise exceptions.ValidationError({"query": "This query parameter is required."})
        limit = self._parse_int_param(request, "limit", required=False, default=10)
        rerank = self._parse_bool_param(request, "rerank", default=False)
        search_limit = limit * 2 if rerank else limit
        results = logic.search_knowledge_for_team(self.team, query.strip(), limit=search_limit)
        if rerank:
            results = logic.rerank_chunks(self.team, query.strip(), results, top_k=limit)
        return Response(KnowledgeSearchResultSerializer(instance=results, many=True).data)

    def _parse_bool_param(self, request: Request, name: str, *, default: bool) -> bool:
        raw = request.query_params.get(name)
        if raw is None:
            return default
        return raw.lower() in ("true", "1", "yes")

    def _parse_int_param(self, request: Request, name: str, *, required: bool, default: int | None = None) -> int:
        raw = request.query_params.get(name)
        if raw is None:
            if required:
                raise exceptions.ValidationError({name: "This query parameter is required."})
            if default is None:
                raise ValueError(f"Non-required param {name!r} must have a non-None default")
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise exceptions.ValidationError({name: "Must be an integer."})


class KnowledgeGapSuggestionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Surfaces topics the support AI couldn't answer from the knowledge base.

    Two list shapes controlled by the ``ticket_id`` query param:
    - **per-ticket** (``?ticket_id=<uuid>``): individual gap rows for that ticket.
    - **aggregated** (no ``ticket_id``): gaps grouped by normalized topic with counts,
      for the Business knowledge suggestions panel.
    """

    scope_object = "business_knowledge"
    queryset = KnowledgeGapSuggestion.objects.unscoped()
    serializer_class = KnowledgeGapSuggestionSerializer
    permission_classes = [IsAuthenticated, APIScopePermission, PostHogFeatureFlagPermission]
    posthog_feature_flag = "product-business-knowledge"
    throttle_classes = [BurstRateThrottle, SustainedRateThrottle]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(team_id=self.team_id)

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        # Any path that exposes data derived from a specific support ticket (topic, status,
        # outcome, ticket type, ticket id) must also require `ticket:read` — `business_knowledge`
        # alone must not be a backdoor to ticket data. This covers the per-ticket list path
        # (`?ticket_id=`) and the single-row `accept`/`dismiss` actions, whose responses serialize
        # the ticket-linked fields. Only applies to token auth; session users are gated by team
        # membership (and already have ticket access via the ticket API). The topic-level
        # `accept_topic`/`dismiss_topic` actions and the aggregated list expose no ticket data, so
        # they fall through to the default `business_knowledge` scope.
        if self.action == "list" and request.query_params.get("ticket_id"):
            return ["business_knowledge:read", "ticket:read"]
        if self.action in ("accept", "dismiss"):
            return ["business_knowledge:write", "ticket:read"]
        return None

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="ticket_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=False,
                description="When provided, returns per-ticket gap rows instead of aggregated view. "
                "Requires `ticket:read` scope in addition to `business_knowledge:read`.",
            ),
        ],
        responses={200: KnowledgeGapSuggestionSerializer(many=True)},
    )
    def list(self, request: Request, **kwargs) -> Response:
        ticket_id = request.query_params.get("ticket_id")
        if ticket_id:
            try:
                UUID(ticket_id)
            except ValueError:
                raise exceptions.ValidationError({"ticket_id": "Must be a valid UUID."})
            suggestions = logic.list_gap_suggestions_for_ticket(self.team_id, ticket_id)
            page = self.paginate_queryset(suggestions)
            if page is not None:
                return self.get_paginated_response(KnowledgeGapSuggestionSerializer(instance=page, many=True).data)
            return Response(KnowledgeGapSuggestionSerializer(instance=suggestions, many=True).data)

        aggregated = logic.aggregate_gap_suggestions(self.team_id)
        return Response(AggregatedGapSerializer(instance=aggregated, many=True).data)

    @extend_schema(
        request=GapActionSerializer,
        responses={200: KnowledgeGapSuggestionSerializer},
    )
    @action(detail=True, methods=["post"], url_path="accept")
    def accept(self, request: Request, **kwargs) -> Response:
        suggestion = self.get_object()
        ser = GapActionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        logic.set_gap_status(
            self.team_id,
            suggestion_id=suggestion.id,
            status=GapStatus.ACCEPTED,
            resolved_source_id=ser.validated_data.get("resolved_source_id"),
        )
        suggestion.refresh_from_db()
        return Response(KnowledgeGapSuggestionSerializer(instance=suggestion).data)

    @extend_schema(
        request=None,
        responses={200: KnowledgeGapSuggestionSerializer},
    )
    @action(detail=True, methods=["post"], url_path="dismiss")
    def dismiss(self, request: Request, **kwargs) -> Response:
        suggestion = self.get_object()
        logic.set_gap_status(
            self.team_id,
            suggestion_id=suggestion.id,
            status=GapStatus.DISMISSED,
        )
        suggestion.refresh_from_db()
        return Response(KnowledgeGapSuggestionSerializer(instance=suggestion).data)

    @extend_schema(
        request=GapTopicActionSerializer,
        responses={200: GapTopicActionResultSerializer},
    )
    @action(detail=False, methods=["post"], url_path="accept_topic")
    def accept_topic(self, request: Request, **kwargs) -> Response:
        """Accept all pending suggestions for a normalized topic cluster."""
        ser = GapTopicActionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        normalized_topic = ser.validated_data["normalized_topic"]
        updated = logic.set_gap_status(
            self.team_id,
            normalized_topic=normalized_topic,
            status=GapStatus.ACCEPTED,
            resolved_source_id=ser.validated_data.get("resolved_source_id"),
            only_pending=True,
        )
        if updated == 0:
            raise exceptions.NotFound("No actionable suggestions found for this topic.")
        return Response({"normalized_topic": normalized_topic, "updated": updated})

    @extend_schema(
        request=GapTopicActionSerializer,
        responses={200: GapTopicActionResultSerializer},
    )
    @action(detail=False, methods=["post"], url_path="dismiss_topic")
    def dismiss_topic(self, request: Request, **kwargs) -> Response:
        """Dismiss all pending suggestions for a normalized topic cluster."""
        ser = GapTopicActionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        normalized_topic = ser.validated_data["normalized_topic"]
        updated = logic.set_gap_status(
            self.team_id,
            normalized_topic=normalized_topic,
            status=GapStatus.DISMISSED,
            only_pending=True,
        )
        if updated == 0:
            raise exceptions.NotFound("No actionable suggestions found for this topic.")
        return Response({"normalized_topic": normalized_topic, "updated": updated})
