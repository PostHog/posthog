from dataclasses import asdict
from functools import partial
from typing import TYPE_CHECKING, cast
from uuid import UUID

from django.shortcuts import get_object_or_404

from drf_spectacular.utils import OpenApiParameter
from prometheus_client import Counter
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.mixins import TypedRequest, ValidatedRequest, validated_request
from posthog.api.monitoring import monitor
from posthog.event_usage import report_user_action
from posthog.permissions import is_service_auth

from products.ai_observability.backend.api.analytics import report_on_commit
from products.ai_observability.backend.api.metrics import llma_track_latency
from products.ai_observability.backend.api.offline_evaluation_base import OfflineEvaluationViewSet
from products.ai_observability.backend.api.offline_experiment_access import (
    OfflineEvaluationIngestionBurstThrottle,
    OfflineEvaluationIngestionSustainedThrottle,
    OfflineEvaluationIngestionTeamBurstThrottle,
    OfflineEvaluationIngestionTeamSustainedThrottle,
)
from products.ai_observability.backend.api.offline_experiment_errors import OfflineEvaluationErrorSerializer
from products.ai_observability.backend.api.offline_experiment_parser import OfflineEvaluationJSONParser
from products.ai_observability.backend.api.offline_experiment_read_serializers import OfflineExperimentReadSerializer
from products.ai_observability.backend.api.offline_experiment_reads import (
    READ_ERROR_RESPONSES,
    OfflineExperimentReadViewSet,
)
from products.ai_observability.backend.api.offline_experiment_serializers import (
    ExperimentSubmissionSerializer,
    UploadSubmissionSerializer,
)
from products.ai_observability.backend.api.resource_tags import ResourceTagNamesField
from products.ai_observability.backend.models.offline_evaluations import OfflineExperiment
from products.ai_observability.backend.offline_evaluation_service import (
    ExperimentReceipt,
    OfflineEvaluationConflict,
    OfflineEvaluationIngestionService,
    OfflineEvaluationNotFound,
    OfflineExperimentService,
)
from products.ai_observability.backend.offline_evaluation_types import ExperimentSubmission, UploadSubmission
from products.ai_observability.backend.resource_tags import ResourceTags

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl

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


class OfflineExperimentMetadataSerializer(serializers.Serializer):
    tags = ResourceTagNamesField(required=False)


class OfflineExperimentViewSet(OfflineExperimentReadViewSet):
    scope_object_write_actions = ["create", "upload", "complete", "fail", "partial_update"]
    psak_allowed_actions = ["create", "upload", "complete", "fail"]
    parser_classes = [OfflineEvaluationJSONParser]
    ingestion_throttle_classes = [
        OfflineEvaluationIngestionBurstThrottle,
        OfflineEvaluationIngestionSustainedThrottle,
        OfflineEvaluationIngestionTeamBurstThrottle,
        OfflineEvaluationIngestionTeamSustainedThrottle,
    ]
    serializer_class = ExperimentSubmissionSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def dangerously_get_required_scopes(self, request: Request, view: viewsets.ViewSetMixin) -> list[str] | None:
        if self.action == "partial_update":
            return ["evaluation:write"]
        if self.action in self.scope_object_write_actions:
            return ["offline_evaluation_ingestion:write"]
        return super().dangerously_get_required_scopes(request, view)

    def get_throttles(self) -> list[BaseThrottle]:
        if self.action in self.psak_allowed_actions:
            return [throttle() for throttle in self.ingestion_throttle_classes]
        return super().get_throttles()

    def _reference_access_control(self) -> "UserAccessControl | None":
        return None if is_service_auth(self.request) else self.user_access_control

    def _report_experiment_action(self, event: str, receipt: ExperimentReceipt) -> None:
        experiment = receipt.experiment
        if experiment.dataset_revision_id is not None:
            dataset_source = "posthog"
        elif experiment.dataset_source:
            dataset_source = "external"
        else:
            dataset_source = "unknown"
        report_on_commit(
            partial(
                report_user_action,
                self.request.user,
                event,
                {
                    "experiment_id": str(experiment.id),
                    "dataset_source": dataset_source,
                    "run_source": experiment.run_source,
                    "status": experiment.status,
                    **asdict(receipt.counts),
                },
                team=self.team,
                request=self.request,
            )
        )

    def handle_exception(self, exc: Exception) -> Response:
        action_name = getattr(self, "action", None)
        if action_name in self.scope_object_read_actions or action_name in {"metadata", "partial_update"}:
            return super().handle_exception(exc)
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
        if isinstance(exc, OfflineEvaluationNotFound):
            exc = NotFound("Experiment not found.")
        response = OfflineEvaluationViewSet.handle_exception(self, exc)
        OFFLINE_UPLOAD_ERRORS.labels(outcome="rejected" if response.status_code < 500 else "server_error").inc()
        return response

    @validated_request(
        request_serializer=OfflineExperimentMetadataSerializer,
        responses={200: OfflineExperimentReadSerializer, **ERROR_RESPONSES, **READ_ERROR_RESPONSES},
        parameters=[EXPERIMENT_ID_PARAMETER],
    )
    def partial_update(self, request: ValidatedRequest, **kwargs: object) -> Response:
        experiment = get_object_or_404(OfflineExperiment.objects.for_team(self.team_id), pk=self._path_id())
        self.check_object_permissions(request, experiment)
        if "tags" in request.validated_data:
            ResourceTags.set(experiment, request.validated_data["tags"])
        return self._read_response(
            lambda: self._read_service().get_experiment(experiment.id), OfflineExperimentReadSerializer
        )

    @validated_request(
        ExperimentSubmissionSerializer,
        responses={200: ExperimentReceiptSerializer, 201: ExperimentReceiptSerializer, **ERROR_RESPONSES},
    )
    @llma_track_latency("aio_offline_experiment_create")
    @monitor(feature=None, endpoint="aio_offline_experiment_create", method="POST")
    def create(self, request: TypedRequest[ExperimentSubmission], **kwargs: object) -> Response:
        receipt = OfflineExperimentService(
            team_id=self.team_id, user_access_control=self._reference_access_control()
        ).create(
            request.validated_data,
            created_by_id=None if is_service_auth(request) else request.user.pk,
        )
        if receipt.created:
            self._report_experiment_action("llma offline experiment created", receipt)
        return _experiment_response(receipt, status=201 if receipt.created else 200)

    def _experiment_id(self) -> UUID:
        return cast(UUID, serializers.UUIDField().run_validation(self.kwargs["pk"]))

    @validated_request(
        UploadSubmissionSerializer,
        parameters=[EXPERIMENT_ID_PARAMETER],
        responses={200: UploadReceiptSerializer, 402: OfflineEvaluationErrorSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    @llma_track_latency("aio_offline_experiment_upload")
    @monitor(feature=None, endpoint="aio_offline_experiment_upload", method="POST")
    def upload(self, request: TypedRequest[UploadSubmission], **kwargs: object) -> Response:
        experiment_id = self._experiment_id()
        receipt = OfflineEvaluationIngestionService(
            team_id=self.team_id, user_access_control=self._reference_access_control()
        ).upload(experiment_id, request.validated_data)
        for created in (True, False):
            OFFLINE_UPLOAD_RESULTS.labels(outcome="created" if created else "duplicate").inc(
                sum(result.created == created for result in receipt.results)
            )
        created_item_count = sum(item.created for item in receipt.items)
        created_result_count = sum(result.created for result in receipt.results)
        if created_item_count or created_result_count:
            report_on_commit(
                partial(
                    report_user_action,
                    request.user,
                    "llma offline experiment results uploaded",
                    {
                        "experiment_id": str(experiment_id),
                        "created_item_count": created_item_count,
                        "created_result_count": created_result_count,
                    },
                    team=self.team,
                    request=request,
                )
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
        receipt = OfflineExperimentService(
            team_id=self.team_id, user_access_control=self._reference_access_control()
        ).close(self._experiment_id(), status="completed")
        if receipt.status_changed:
            self._report_experiment_action("llma offline experiment completed", receipt)
        return _experiment_response(receipt)

    @validated_request(
        EmptyOfflineExperimentSerializer,
        parameters=[EXPERIMENT_ID_PARAMETER],
        responses={200: ExperimentReceiptSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    @llma_track_latency("aio_offline_experiment_fail")
    @monitor(feature=None, endpoint="aio_offline_experiment_fail", method="POST")
    def fail(self, request: Request, **kwargs: object) -> Response:
        receipt = OfflineExperimentService(
            team_id=self.team_id, user_access_control=self._reference_access_control()
        ).close(self._experiment_id(), status="failed")
        if receipt.status_changed:
            self._report_experiment_action("llma offline experiment failed", receipt)
        return _experiment_response(receipt)
