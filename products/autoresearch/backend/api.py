from typing import Any

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.autoresearch.backend.inference import run_inference_for_pipeline
from products.autoresearch.backend.models import (
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchRun,
    AutoresearchTrainingRun,
)
from products.autoresearch.backend.serializers import (
    AutoresearchModelSerializer,
    AutoresearchPipelineCreateSerializer,
    AutoresearchPipelineSerializer,
    AutoresearchRunSerializer,
    AutoresearchTrainingRunSerializer,
    StartTrainingRequestSerializer,
    ValidatePipelineRequestSerializer,
    ValidatePipelineResponseSerializer,
)
from products.autoresearch.backend.stub_training import run_stub_training
from products.autoresearch.backend.validation import validate_pipeline_definition

logger = structlog.get_logger(__name__)


@extend_schema(tags=["autoresearch"])
class AutoresearchPipelineViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Manage autoresearch prediction pipelines.

    A pipeline defines a target event, population, and horizon. The autoresearch
    training loop finds the best predictive recipe; the inference workflow scores
    users daily and emits autoresearch_prediction events.
    """

    scope_object = "INTERNAL"
    serializer_class = AutoresearchPipelineSerializer
    queryset = AutoresearchPipeline.objects.all()

    def safely_get_queryset(self, queryset: Any) -> Any:
        return queryset.filter(team=self.team).exclude(status=AutoresearchPipeline.Status.ARCHIVED)

    def get_serializer_class(self) -> type[AutoresearchPipelineSerializer | AutoresearchPipelineCreateSerializer]:
        if self.action in ("create", "partial_update", "update"):
            return AutoresearchPipelineCreateSerializer
        return AutoresearchPipelineSerializer

    def perform_create(self, serializer: Any) -> None:
        serializer.save(
            team=self.team,
            created_by=self.request.user,
            iteration_budget_remaining=serializer.validated_data.get("iteration_budget", 50),
        )

    @validated_request(
        request_serializer=ValidatePipelineRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=ValidatePipelineResponseSerializer,
                description="Validation result with volume estimates, base rate, and warnings.",
            ),
        },
        summary="Validate a pipeline definition",
        description=(
            "Validate a proposed pipeline's target event and population before creating it. "
            "Returns volume estimates, base rate, and any warnings. "
            "Warnings with severity='error' must be resolved before creation can proceed. "
            "Call this before autoresearch-create."
        ),
    )
    @action(detail=False, methods=["post"], url_path="validate")
    def validate_definition(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        data = request.validated_data  # type: ignore[attr-defined]
        result = validate_pipeline_definition(
            team=self.team,
            target_event=data["target_event"],
            horizon_days=data.get("horizon_days", 7),
            prediction_mode=data.get("prediction_mode", "adoption"),
            training_population=data.get("training_population", {}),
            inference_population=data.get("inference_population", {}),
        )
        response_serializer = ValidatePipelineResponseSerializer(
            {
                "can_proceed": result.can_proceed,
                "requires_acknowledgement": result.requires_acknowledgement,
                "estimated_training_rows": result.estimated_training_rows,
                "positive_count": result.positive_count,
                "negative_count": result.negative_count,
                "base_rate": result.base_rate,
                "inference_population_size": result.inference_population_size,
                "warnings": [{"code": w.code, "message": w.message, "severity": w.severity} for w in result.warnings],
                "error": result.error,
            }
        )
        return Response(response_serializer.data)

    @validated_request(
        request_serializer=StartTrainingRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=AutoresearchTrainingRunSerializer,
                description="The created training run. Poll status via the runs list endpoint.",
            ),
            400: OpenApiResponse(description="Pipeline is not in a state that allows training to start."),
        },
        summary="Start a training run",
        description=(
            "Trigger a training run for this pipeline. In production this creates a Task/TaskRun "
            "sandbox and starts the autoresearch loop. In the stub implementation it synchronously "
            "creates a hand-authored champion recipe and marks the run as completed."
        ),
    )
    @action(detail=True, methods=["post"], url_path="train")
    def start_training(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        pipeline = self.get_object()
        if pipeline.status == AutoresearchPipeline.Status.ARCHIVED:
            raise ValidationError("Cannot start training on an archived pipeline.")

        data = request.validated_data  # type: ignore[attr-defined]
        budget = data.get("iteration_budget") or pipeline.iteration_budget

        training_run = run_stub_training(pipeline=pipeline, iteration_budget=budget)
        return Response(AutoresearchTrainingRunSerializer(training_run).data)

    @validated_request(
        responses={
            200: OpenApiResponse(
                response=AutoresearchRunSerializer,
                description="The created inference run. Check rows_scored and status.",
            ),
            400: OpenApiResponse(description="Pipeline has no champion model or is archived."),
        },
        summary="Run inference (score users)",
        description=(
            "Score the inference population using the champion model and emit autoresearch_prediction "
            "events for each scored user. Updates the predicted_p_<target> person property. "
            "In production this is triggered by the daily Temporal inference workflow."
        ),
    )
    @action(detail=True, methods=["post"], url_path="score")
    def run_inference(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        pipeline = self.get_object()
        if pipeline.status == AutoresearchPipeline.Status.ARCHIVED:
            raise ValidationError("Cannot score an archived pipeline.")

        champion = (
            AutoresearchModel.objects.filter(pipeline=pipeline, role=AutoresearchModel.Role.CHAMPION)
            .order_by("-created_at")
            .first()
        )
        if not champion:
            raise ValidationError("No champion model found. Run training first.")

        run = run_inference_for_pipeline(pipeline=pipeline, model=champion)
        return Response(AutoresearchRunSerializer(run).data)

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=AutoresearchPipelineSerializer,
                description="The pipeline after archiving.",
            ),
        },
        summary="Archive a pipeline",
        description="Soft-delete a pipeline. Stops daily scoring and training. Predictions and metrics are preserved.",
    )
    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        pipeline = self.get_object()
        pipeline.status = AutoresearchPipeline.Status.ARCHIVED
        pipeline.save(update_fields=["status", "updated_at"])
        return Response(AutoresearchPipelineSerializer(pipeline).data)

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=AutoresearchPipelineSerializer,
                description="The pipeline after pausing.",
            ),
        },
        summary="Pause a pipeline",
        description="Pause daily scoring and training. The pipeline can be resumed later.",
    )
    @action(detail=True, methods=["post"], url_path="pause")
    def pause(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        pipeline = self.get_object()
        pipeline.status = AutoresearchPipeline.Status.PAUSED
        pipeline.save(update_fields=["status", "updated_at"])
        return Response(AutoresearchPipelineSerializer(pipeline).data)

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=AutoresearchPipelineSerializer,
                description="The pipeline after resuming.",
            ),
        },
        summary="Resume a pipeline",
        description="Resume a paused pipeline. Daily scoring and training will restart on the next cadence tick.",
    )
    @action(detail=True, methods=["post"], url_path="resume")
    def resume(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        pipeline = self.get_object()
        if pipeline.status != AutoresearchPipeline.Status.PAUSED:
            raise ValidationError("Pipeline is not paused.")
        pipeline.status = AutoresearchPipeline.Status.RUNNING
        pipeline.save(update_fields=["status", "updated_at"])
        return Response(AutoresearchPipelineSerializer(pipeline).data)


@extend_schema(tags=["autoresearch"])
class AutoresearchModelViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    List and retrieve champion/challenger models for a pipeline.

    Models are the persisted artifacts produced by training runs. Each model
    holds a portable recipe (feature SQL, transforms, model class, params) that
    the daily inference workflow compiles to score users.
    """

    scope_object = "INTERNAL"
    serializer_class = AutoresearchModelSerializer
    queryset = AutoresearchModel.objects.all()

    def _should_skip_parents_filter(self) -> bool:
        return True

    def safely_get_queryset(self, queryset: Any) -> Any:
        pipeline_id = self.kwargs.get("parent_lookup_pipeline_id")
        qs = queryset.filter(pipeline__team=self.team).select_related("pipeline")
        if pipeline_id:
            qs = qs.filter(pipeline_id=pipeline_id)
        return qs.order_by("-created_at")


@extend_schema(tags=["autoresearch"])
class AutoresearchRunViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    List and retrieve inference, validation, and notebook runs for a pipeline.
    """

    scope_object = "INTERNAL"
    serializer_class = AutoresearchRunSerializer
    queryset = AutoresearchRun.objects.all()

    def _should_skip_parents_filter(self) -> bool:
        return True

    def safely_get_queryset(self, queryset: Any) -> Any:
        pipeline_id = self.kwargs.get("parent_lookup_pipeline_id")
        qs = queryset.filter(pipeline__team=self.team).select_related("pipeline", "model")
        if pipeline_id:
            qs = qs.filter(pipeline_id=pipeline_id)
        return qs.order_by("-created_at")


@extend_schema(tags=["autoresearch"])
class AutoresearchTrainingRunViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    List and retrieve training runs for a pipeline.
    """

    scope_object = "INTERNAL"
    serializer_class = AutoresearchTrainingRunSerializer
    queryset = AutoresearchTrainingRun.objects.all()

    def _should_skip_parents_filter(self) -> bool:
        return True

    def safely_get_queryset(self, queryset: Any) -> Any:
        pipeline_id = self.kwargs.get("parent_lookup_pipeline_id")
        qs = queryset.filter(pipeline__team=self.team).select_related("pipeline")
        if pipeline_id:
            qs = qs.filter(pipeline_id=pipeline_id)
        return qs.order_by("-created_at")
