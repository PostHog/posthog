from collections.abc import Callable
from typing import cast
from uuid import UUID

from django.db import router

from drf_spectacular.utils import OpenApiParameter
from prometheus_client import Counter
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.statement_timeout import statement_timeout
from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.permissions import AccessControlPermission, PostHogFeatureFlagPermission, get_authenticator_scopes

from products.ai_observability.backend.api.metrics import llma_track_latency
from products.ai_observability.backend.api.offline_experiment_access import (
    OfflineEvaluationReadBurstThrottle,
    OfflineEvaluationReadSustainedThrottle,
    OfflineEvaluationReadTeamBurstThrottle,
    OfflineEvaluationReadTeamSustainedThrottle,
)
from products.ai_observability.backend.api.offline_experiment_errors import (
    OfflineEvaluationErrorSerializer,
    validation_errors,
)
from products.ai_observability.backend.api.offline_experiment_read_serializers import (
    OfflineEmptyQuerySerializer,
    OfflineExperimentPageSerializer,
    OfflineExperimentQuerySerializer,
    OfflineExperimentReadSerializer,
    OfflineHistoryPageSerializer,
    OfflineItemPageSerializer,
    OfflineItemPayloadReadSerializer,
    OfflineItemReadSerializer,
    OfflineResultPageSerializer,
    OfflineResultPayloadReadSerializer,
    OfflineResultQuerySerializer,
    OfflineSummaryPageSerializer,
    OfflineSummaryQuerySerializer,
)
from products.ai_observability.backend.models.offline_evaluations import OfflineExperiment
from products.ai_observability.backend.offline_evaluation_read_service import OfflineEvaluationReadService
from products.ai_observability.backend.offline_evaluation_read_types import OfflineReadQuery
from products.ai_observability.backend.offline_evaluation_service import (
    OfflineEvaluationNotFound,
    OfflineEvaluationValidationError,
)

OFFLINE_READ_ERRORS = Counter(
    "aio_offline_read_errors_total", "Rejected offline evaluation reads", labelnames=["outcome"]
)
OFFLINE_READ_TIMEOUTS = Counter(
    "aio_offline_read_timeouts_total", "Offline evaluation read statements exceeding their budget"
)
READ_ERROR_RESPONSES = dict.fromkeys((400, 401, 403, 404, 429, 503), OfflineEvaluationErrorSerializer)
EXPERIMENT_ID_PARAMETER = OpenApiParameter("id", UUID, OpenApiParameter.PATH, description="Experiment UUID.")
ITEM_ID_PARAMETER = OpenApiParameter(
    "item_id", UUID, OpenApiParameter.PATH, description="Item UUID within the experiment."
)
RESULT_ID_PARAMETER = OpenApiParameter(
    "result_id", UUID, OpenApiParameter.PATH, description="Result UUID within the experiment."
)


class OfflineReadTimedOut(APIException):
    status_code = 503
    default_code = "offline_evaluation_query_timeout"
    default_detail = "This offline evaluation query took too long. Narrow the filters and try again."


class OfflineEvaluationReadViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "evaluation"
    scope_object_read_actions = [
        "list",
        "retrieve",
        "items",
        "item",
        "item_results",
        "item_payload",
        "result_payload",
        "scorer_summaries",
        "history",
    ]
    requires_resource_level_access = True
    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    psak_allowed_actions: list[str] = []
    permission_classes = [AccessControlPermission, PostHogFeatureFlagPermission]
    posthog_feature_flag = "ai-observability-offline-evaluations"
    serializer_class: type[serializers.Serializer] = OfflineExperimentReadSerializer
    http_method_names = ["get", "head", "options"]
    pagination_class = None

    def dangerously_get_required_scopes(self, request: Request, view: viewsets.ViewSetMixin) -> list[str] | None:
        if self.action in ["create", "upload", "complete", "fail"]:
            return ["offline_evaluation_ingestion:write"]
        if self.action in ["item_results", "result_payload", "scorer_summaries", "history"]:
            return ["evaluation:read", "llm_analytics:read"]
        if self.action in self.scope_object_read_actions or request.method == "OPTIONS":
            return ["evaluation:read"]
        return None

    def get_throttles(self) -> list[BaseThrottle]:
        if self.request.method not in ["GET", "HEAD", "OPTIONS"]:
            return super().get_throttles()
        return [
            OfflineEvaluationReadBurstThrottle(),
            OfflineEvaluationReadSustainedThrottle(),
            OfflineEvaluationReadTeamBurstThrottle(),
            OfflineEvaluationReadTeamSustainedThrottle(),
        ]

    def handle_exception(self, exc: Exception) -> Response:
        request = getattr(self, "request", None)
        if request is None or request.method not in ["GET", "HEAD", "OPTIONS"]:
            return super().handle_exception(exc)
        if isinstance(exc, OfflineEvaluationNotFound):
            exc = NotFound("Offline evaluation resource not found.")
        elif isinstance(exc, OfflineEvaluationValidationError):
            exc = ValidationError(exc.errors)
        response = super().handle_exception(exc)
        if isinstance(exc, ValidationError):
            errors = validation_errors(exc.detail)
            if errors:
                response.data.update(errors[0], errors=errors)
        OFFLINE_READ_ERRORS.labels(outcome="rejected" if response.status_code < 500 else "server_error").inc()
        return response

    def _read_service(self, query: OfflineReadQuery | None = None) -> OfflineEvaluationReadService:
        if self.action in ["retrieve", "item", "item_payload", "result_payload"]:
            OfflineEmptyQuerySerializer(data=self.request.query_params).is_valid(raise_exception=True)
        scopes = get_authenticator_scopes(self.request.successful_authenticator)
        can_read_scores = scopes is None or bool(
            {"*", "llm_analytics:read", "llm_analytics:write"}.intersection(scopes)
        )
        if query is not None and (query.scorer_definition_id or query.scorer_version_ids) and not can_read_scores:
            raise PermissionDenied("Scorer filters require llm_analytics:read.")
        return OfflineEvaluationReadService(
            team_id=self.team_id, user_access_control=self.user_access_control, can_read_scores=can_read_scores
        )

    def _path_id(self, name: str = "pk") -> UUID:
        return cast(UUID, serializers.UUIDField().run_validation(self.kwargs[name]))

    def _read_response(self, read: Callable[[], object], serializer: type[serializers.Serializer]) -> Response:
        with statement_timeout(
            router.db_for_read(OfflineExperiment), 10_000, OfflineReadTimedOut, OFFLINE_READ_TIMEOUTS
        ):
            return Response(serializer(read()).data)


class OfflineExperimentReadViewSet(OfflineEvaluationReadViewSet):
    @validated_request(
        query_serializer=OfflineExperimentQuerySerializer,
        responses={200: OfflineExperimentPageSerializer, **READ_ERROR_RESPONSES},
    )
    @llma_track_latency("aio_offline_experiment_list")
    @monitor(feature=None, endpoint="aio_offline_experiment_list", method="GET")
    def list(self, request: ValidatedRequest, **kwargs: object) -> Response:
        query = cast(OfflineReadQuery, request.validated_query_data)
        service = self._read_service(query)
        return self._read_response(lambda: service.list_experiments(query), OfflineExperimentPageSerializer)

    @validated_request(
        parameters=[EXPERIMENT_ID_PARAMETER],
        responses={200: OfflineExperimentReadSerializer, **READ_ERROR_RESPONSES},
    )
    @llma_track_latency("aio_offline_experiment_retrieve")
    @monitor(feature=None, endpoint="aio_offline_experiment_retrieve", method="GET")
    def retrieve(self, request: Request, **kwargs: object) -> Response:
        return self._read_response(
            lambda: self._read_service().get_experiment(self._path_id()), OfflineExperimentReadSerializer
        )

    @validated_request(
        query_serializer=OfflineResultQuerySerializer,
        operation_id="ai_observability_offline_experiments_items_list",
        parameters=[EXPERIMENT_ID_PARAMETER],
        responses={200: OfflineItemPageSerializer, **READ_ERROR_RESPONSES},
    )
    @action(detail=True, methods=["get"])
    @llma_track_latency("aio_offline_experiment_items")
    @monitor(feature=None, endpoint="aio_offline_experiment_items", method="GET")
    def items(self, request: ValidatedRequest, **kwargs: object) -> Response:
        query = cast(OfflineReadQuery, request.validated_query_data)
        service = self._read_service(query)
        return self._read_response(lambda: service.list_items(self._path_id(), query), OfflineItemPageSerializer)

    @validated_request(
        parameters=[EXPERIMENT_ID_PARAMETER, ITEM_ID_PARAMETER],
        responses={200: OfflineItemReadSerializer, **READ_ERROR_RESPONSES},
    )
    @action(detail=True, methods=["get"], url_path=r"items/(?P<item_id>[^/.]+)")
    @llma_track_latency("aio_offline_experiment_item")
    @monitor(feature=None, endpoint="aio_offline_experiment_item", method="GET")
    def item(self, request: Request, **kwargs: object) -> Response:
        return self._read_response(
            lambda: self._read_service().get_item(self._path_id(), self._path_id("item_id")), OfflineItemReadSerializer
        )

    @validated_request(
        query_serializer=OfflineSummaryQuerySerializer,
        parameters=[EXPERIMENT_ID_PARAMETER, ITEM_ID_PARAMETER],
        responses={200: OfflineResultPageSerializer, **READ_ERROR_RESPONSES},
    )
    @action(detail=True, methods=["get"], url_path=r"items/(?P<item_id>[^/.]+)/results")
    @llma_track_latency("aio_offline_item_results")
    @monitor(feature=None, endpoint="aio_offline_item_results", method="GET")
    def item_results(self, request: ValidatedRequest, **kwargs: object) -> Response:
        query = cast(OfflineReadQuery, request.validated_query_data)
        service = self._read_service(query)
        return self._read_response(
            lambda: service.list_item_results(self._path_id(), self._path_id("item_id"), query),
            OfflineResultPageSerializer,
        )

    @validated_request(
        parameters=[EXPERIMENT_ID_PARAMETER, ITEM_ID_PARAMETER],
        responses={200: OfflineItemPayloadReadSerializer, **READ_ERROR_RESPONSES},
    )
    @action(detail=True, methods=["get"], url_path=r"items/(?P<item_id>[^/.]+)/payload")
    @llma_track_latency("aio_offline_item_payload")
    @monitor(feature=None, endpoint="aio_offline_item_payload", method="GET")
    def item_payload(self, request: Request, **kwargs: object) -> Response:
        return self._read_response(
            lambda: self._read_service().get_item_payload(self._path_id(), self._path_id("item_id")),
            OfflineItemPayloadReadSerializer,
        )

    @validated_request(
        parameters=[EXPERIMENT_ID_PARAMETER, RESULT_ID_PARAMETER],
        responses={200: OfflineResultPayloadReadSerializer, **READ_ERROR_RESPONSES},
    )
    @action(detail=True, methods=["get"], url_path=r"results/(?P<result_id>[^/.]+)/payload")
    @llma_track_latency("aio_offline_result_payload")
    @monitor(feature=None, endpoint="aio_offline_result_payload", method="GET")
    def result_payload(self, request: Request, **kwargs: object) -> Response:
        return self._read_response(
            lambda: self._read_service().get_result_payload(self._path_id(), self._path_id("result_id")),
            OfflineResultPayloadReadSerializer,
        )

    @validated_request(
        query_serializer=OfflineSummaryQuerySerializer,
        parameters=[EXPERIMENT_ID_PARAMETER],
        responses={200: OfflineSummaryPageSerializer, **READ_ERROR_RESPONSES},
    )
    @action(detail=True, methods=["get"])
    @llma_track_latency("aio_offline_scorer_summaries")
    @monitor(feature=None, endpoint="aio_offline_scorer_summaries", method="GET")
    def scorer_summaries(self, request: ValidatedRequest, **kwargs: object) -> Response:
        query = cast(OfflineReadQuery, request.validated_query_data)
        service = self._read_service(query)
        return self._read_response(lambda: service.list_summaries(self._path_id(), query), OfflineSummaryPageSerializer)


class OfflineScorerViewSet(OfflineEvaluationReadViewSet):
    @validated_request(
        query_serializer=OfflineExperimentQuerySerializer,
        parameters=[OpenApiParameter("id", UUID, OpenApiParameter.PATH, description="Scorer definition UUID.")],
        responses={200: OfflineHistoryPageSerializer, **READ_ERROR_RESPONSES},
    )
    @action(detail=True, methods=["get"])
    @llma_track_latency("aio_offline_scorer_history")
    @monitor(feature=None, endpoint="aio_offline_scorer_history", method="GET")
    def history(self, request: ValidatedRequest, **kwargs: object) -> Response:
        query = cast(OfflineReadQuery, request.validated_query_data)
        service = self._read_service(query)
        return self._read_response(lambda: service.scorer_history(self._path_id(), query), OfflineHistoryPageSerializer)
