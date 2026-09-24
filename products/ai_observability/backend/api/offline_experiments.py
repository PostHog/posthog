from dataclasses import asdict
from typing import cast
from uuid import UUID

from drf_spectacular.utils import OpenApiParameter
from prometheus_client import Counter
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import TypedRequest, validated_request
from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.permissions import AccessControlPermission, PostHogFeatureFlagPermission

from products.ai_observability.backend.api.metrics import llma_track_latency
from products.ai_observability.backend.api.offline_experiment_access import (
    OfflineEvaluationIngestionBurstThrottle,
    OfflineEvaluationIngestionSustainedThrottle,
    OfflineEvaluationIngestionTeamBurstThrottle,
    OfflineEvaluationIngestionTeamSustainedThrottle,
)
from products.ai_observability.backend.api.offline_experiment_parser import OfflineEvaluationJSONParser
from products.ai_observability.backend.api.offline_experiment_serializers import (
    ExperimentSubmissionSerializer,
    UploadSubmissionSerializer,
)
from products.ai_observability.backend.models.offline_evaluations import OfflineExperiment
from products.ai_observability.backend.offline_evaluation_service import (
    ExperimentReceipt,
    OfflineEvaluationConflict,
    OfflineEvaluationIngestionService,
    OfflineEvaluationNotFound,
    OfflineEvaluationValidationError,
    OfflineExperimentService,
)
from products.ai_observability.backend.offline_evaluation_types import ExperimentSubmission, UploadSubmission

OFFLINE_UPLOAD_RESULTS = Counter(
    "aio_offline_upload_results_total", "Acknowledged offline evaluation results", labelnames=["outcome"]
)
OFFLINE_UPLOAD_ERRORS = Counter(
    "aio_offline_upload_errors_total", "Rejected offline evaluation API requests", labelnames=["outcome"]
)


class ExperimentReceiptSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Stable experiment UUID supplied at creation.")
    status = serializers.ChoiceField(
        choices=OfflineExperiment.Status.choices, help_text="Current upload lifecycle state."
    )
    created = serializers.BooleanField(help_text="Whether this request created the experiment.")
    started_at = serializers.DateTimeField(help_text="Caller-supplied execution start time.")
    created_at = serializers.DateTimeField(help_text="Time the experiment was first accepted.")
    finished_at = serializers.DateTimeField(allow_null=True, help_text="Server closure time; null while uploading.")
    expected_item_count = serializers.IntegerField(allow_null=True, help_text="Declared item count, when supplied.")
    expected_result_count = serializers.IntegerField(allow_null=True, help_text="Declared result count, when supplied.")
    accepted_item_count = serializers.IntegerField(help_text="Number of unique accepted items.")
    accepted_result_count = serializers.IntegerField(help_text="Number of unique accepted results across all statuses.")


class ItemReceiptSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Accepted item UUID.")
    created = serializers.BooleanField(help_text="Whether this upload created the item.")
    accepted_at = serializers.DateTimeField(help_text="Original server acceptance time, unchanged on retry.")


class ResultReceiptSerializer(ItemReceiptSerializer):
    item_id = serializers.UUIDField(help_text="Item this result evaluates.")
    scorer_version_id = serializers.UUIDField(help_text="Pinned scorer version used by this result.")


class UploadReceiptSerializer(serializers.Serializer):
    items = ItemReceiptSerializer(many=True, help_text="One acknowledgment per referenced item.")
    results = ResultReceiptSerializer(many=True, help_text="Acknowledgments in the submitted result order.")


class OfflineEvaluationErrorSerializer(serializers.Serializer):
    type = serializers.CharField(required=False, help_text="Error category for standard API errors.")
    code = serializers.CharField(help_text="Stable error code.")
    detail = serializers.CharField(help_text="Explanation of the rejected request.")
    attr = serializers.CharField(
        required=False, allow_null=True, help_text="Invalid field, including batch entry index."
    )
    expected_item_count = serializers.IntegerField(required=False, allow_null=True, help_text="Declared item count.")
    expected_result_count = serializers.IntegerField(
        required=False, allow_null=True, help_text="Declared result count."
    )
    accepted_item_count = serializers.IntegerField(required=False, help_text="Accepted items at failed completion.")
    accepted_result_count = serializers.IntegerField(required=False, help_text="Accepted results at failed completion.")


class EmptyOfflineExperimentSerializer(serializers.Serializer):
    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        if self.initial_data:
            raise serializers.ValidationError("This operation does not accept fields.")
        return attrs


def _experiment_response(receipt: ExperimentReceipt, *, status: int = 200) -> Response:
    experiment = receipt.experiment
    return Response(
        ExperimentReceiptSerializer(
            {
                "id": experiment.id,
                "status": experiment.status,
                "created": receipt.created,
                "started_at": experiment.started_at,
                "created_at": experiment.created_at,
                "finished_at": experiment.finished_at,
                **asdict(receipt.counts),
            }
        ).data,
        status=status,
    )


ERROR_RESPONSES = dict.fromkeys((400, 401, 403, 404, 409, 413, 429), OfflineEvaluationErrorSerializer)


EXPERIMENT_ID_PARAMETER = OpenApiParameter("id", UUID, OpenApiParameter.PATH, description="Experiment UUID.")


class OfflineExperimentViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "evaluation"
    required_scopes = ["offline_evaluation_ingestion:write"]
    scope_object_write_actions = ["create", "upload", "complete", "fail"]
    requires_resource_level_access = True
    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    psak_allowed_actions = ["create", "upload", "complete", "fail"]
    permission_classes = [AccessControlPermission, PostHogFeatureFlagPermission]
    posthog_feature_flag = "ai-observability-offline-evaluations"
    parser_classes = [OfflineEvaluationJSONParser]
    throttle_classes = [
        OfflineEvaluationIngestionBurstThrottle,
        OfflineEvaluationIngestionSustainedThrottle,
        OfflineEvaluationIngestionTeamBurstThrottle,
        OfflineEvaluationIngestionTeamSustainedThrottle,
    ]
    serializer_class = ExperimentSubmissionSerializer
    http_method_names = ["post", "head", "options"]

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, OfflineEvaluationConflict):
            OFFLINE_UPLOAD_ERRORS.labels(outcome="conflict").inc()
            return Response(
                OfflineEvaluationErrorSerializer(
                    {
                        "code": exc.code,
                        "detail": exc.detail,
                        "attr": exc.field,
                        **(asdict(exc.counts) if exc.counts else {}),
                    }
                ).data,
                status=409,
            )
        if isinstance(exc, OfflineEvaluationValidationError):
            exc = ValidationError({exc.field: exc.detail})
        elif isinstance(exc, OfflineEvaluationNotFound):
            exc = NotFound("Experiment not found.")
        response = super().handle_exception(exc)
        OFFLINE_UPLOAD_ERRORS.labels(outcome="rejected" if response.status_code < 500 else "server_error").inc()
        return response

    @validated_request(
        ExperimentSubmissionSerializer,
        responses={200: ExperimentReceiptSerializer, 201: ExperimentReceiptSerializer, **ERROR_RESPONSES},
    )
    @llma_track_latency("aio_offline_experiment_create")
    @monitor(feature=None, endpoint="aio_offline_experiment_create", method="POST")
    def create(self, request: TypedRequest[ExperimentSubmission], **kwargs: object) -> Response:
        receipt = OfflineExperimentService(team_id=self.team_id).create(request.validated_data)
        return _experiment_response(receipt, status=201 if receipt.created else 200)

    def _experiment_id(self) -> UUID:
        return cast(UUID, serializers.UUIDField().run_validation(self.kwargs["pk"]))

    @validated_request(
        UploadSubmissionSerializer,
        parameters=[EXPERIMENT_ID_PARAMETER],
        responses={200: UploadReceiptSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    @llma_track_latency("aio_offline_experiment_upload")
    @monitor(feature=None, endpoint="aio_offline_experiment_upload", method="POST")
    def upload(self, request: TypedRequest[UploadSubmission], **kwargs: object) -> Response:
        receipt = OfflineEvaluationIngestionService(team_id=self.team_id).upload(
            self._experiment_id(), request.validated_data
        )
        for created in (True, False):
            OFFLINE_UPLOAD_RESULTS.labels(outcome="created" if created else "duplicate").inc(
                sum(result.created == created for result in receipt.results)
            )
        return Response(UploadReceiptSerializer(receipt).data)

    @validated_request(
        EmptyOfflineExperimentSerializer,
        parameters=[EXPERIMENT_ID_PARAMETER],
        responses={200: ExperimentReceiptSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    @llma_track_latency("aio_offline_experiment_complete")
    @monitor(feature=None, endpoint="aio_offline_experiment_complete", method="POST")
    def complete(self, request: Request, **kwargs: object) -> Response:
        return _experiment_response(
            OfflineExperimentService(team_id=self.team_id).close(self._experiment_id(), status="completed")
        )

    @validated_request(
        EmptyOfflineExperimentSerializer,
        parameters=[EXPERIMENT_ID_PARAMETER],
        responses={200: ExperimentReceiptSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    @llma_track_latency("aio_offline_experiment_fail")
    @monitor(feature=None, endpoint="aio_offline_experiment_fail", method="POST")
    def fail(self, request: Request, **kwargs: object) -> Response:
        return _experiment_response(
            OfflineExperimentService(team_id=self.team_id).close(self._experiment_id(), status="failed")
        )
