from typing import Any

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.autoresearch.backend.access import has_autoresearch_access
from products.autoresearch.backend.inference import run_inference_for_pipeline
from products.autoresearch.backend.models import (
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchRun,
    AutoresearchSuggestion,
    AutoresearchTrainingRun,
)
from products.autoresearch.backend.online_validation import run_online_validation_for_pipeline
from products.autoresearch.backend.serializers import (
    AutoresearchModelSerializer,
    AutoresearchPipelineCreateSerializer,
    AutoresearchPipelineSerializer,
    AutoresearchRunSerializer,
    AutoresearchSuggestionSerializer,
    AutoresearchTrainingRunSerializer,
    CreateSuggestionSerializer,
    ResolvedTemplateSerializer,
    ResolveTemplateRequestSerializer,
    StartTrainingRequestSerializer,
    TemplateInfoSerializer,
    ValidatePipelineRequestSerializer,
    ValidatePipelineResponseSerializer,
)
from products.autoresearch.backend.templates import (
    TEMPLATES,
    resolve_template as resolve_template_def,
)
from products.autoresearch.backend.training import run_training
from products.autoresearch.backend.validation import validate_pipeline_definition

logger = structlog.get_logger(__name__)


class AutoresearchAccessPermission(BasePermission):
    """Gate the autoresearch product behind the `autoresearch` feature flag."""

    message = "Autoresearch is not enabled for this team."

    def has_permission(self, request: Request, view: APIView) -> bool:
        team_id = getattr(view, "team_id", None)
        return has_autoresearch_access(request.user, team_id=team_id)


@extend_schema(tags=["autoresearch"])
class AutoresearchPipelineViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Manage autoresearch prediction pipelines.

    A pipeline defines a target event, population, and horizon. The autoresearch
    training loop finds the best predictive recipe; the inference workflow scores
    users daily and emits autoresearch_prediction events.
    """

    scope_object = "autoresearch"
    scope_object_read_actions = ["list", "retrieve", "validate_definition", "list_templates", "resolve_template"]
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "destroy",
        "start_training",
        "run_inference",
        "run_validation",
        "archive",
        "pause",
        "resume",
    ]
    permission_classes = [AutoresearchAccessPermission]
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

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        # Return full representation using the read serializer
        output = AutoresearchPipelineSerializer(serializer.instance, context=self.get_serializer_context())
        headers = self.get_success_headers(output.data)
        return Response(output.data, status=201, headers=headers)

    @extend_schema(
        responses={200: TemplateInfoSerializer(many=True)},
        summary="List available templates",
        description=(
            "Return all built-in autoresearch prediction templates. "
            "Each entry describes what the template predicts, its default horizon and prediction mode, "
            "and whether it requires you to supply a target_event. "
            "After choosing a template, call autoresearch-resolve-template-create to get a fully "
            "resolved pipeline config ready to pass to autoresearch-create."
        ),
    )
    @action(detail=False, methods=["get"], url_path="templates")
    def list_templates(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = TemplateInfoSerializer(
            [
                {
                    "key": t.key,
                    "display_name": t.display_name,
                    "description": t.description,
                    "prediction_mode": t.prediction_mode,
                    "default_horizon_days": t.default_horizon_days,
                    "requires_user_event": t.requires_user_event,
                    "requires_activity_resolution": t.requires_activity_resolution,
                    "notes": t.notes,
                }
                for t in TEMPLATES.values()
            ],
            many=True,
        )
        return Response(serializer.data)

    @validated_request(
        request_serializer=ResolveTemplateRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=ResolvedTemplateSerializer,
                description=(
                    "Resolved pipeline config. Pass target_event, prediction_mode, horizon_days, "
                    "training_population, inference_population, and output_person_property directly "
                    "to autoresearch-create. Always run autoresearch-validate-create on the resolved "
                    "config before creating."
                ),
            ),
            400: OpenApiResponse(
                description="Unknown template key or missing required target_event override.",
            ),
        },
        summary="Resolve a template",
        description=(
            "Resolve a template key and optional overrides into a concrete pipeline config. "
            "For activity-based templates ('likely_active_soon', 'at_risk_of_inactivity', "
            "'return_after_first_use'), the target event is auto-resolved from your event schema — "
            "check resolved_activity_event and activity_event_alternatives, then override if needed. "
            "For 'feature_adoption' and 'repeat_key_behavior', supply target_event. "
            "After resolving, call autoresearch-validate-create to check volume and warnings, "
            "then autoresearch-create to create the pipeline."
        ),
    )
    @action(detail=False, methods=["post"], url_path="resolve-template")
    def resolve_template(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        data = request.validated_data  # type: ignore[attr-defined]
        try:
            resolved = resolve_template_def(
                team=self.team,
                template_key=data["template_key"],
                target_event_override=data.get("target_event"),
                horizon_days_override=data.get("horizon_days"),
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        response_serializer = ResolvedTemplateSerializer(
            {
                "template_key": resolved.template_key,
                "display_name": resolved.display_name,
                "description": resolved.description,
                "suggested_name": resolved.suggested_name,
                "target_event": resolved.target_event,
                "resolved_activity_event": resolved.resolved_activity_event,
                "activity_event_alternatives": resolved.activity_event_alternatives,
                "prediction_mode": resolved.prediction_mode,
                "horizon_days": resolved.horizon_days,
                "training_population": resolved.training_population,
                "inference_population": resolved.inference_population,
                "output_person_property": resolved.output_person_property,
                "notes": resolved.notes,
            }
        )
        return Response(response_serializer.data)

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

        training_run = run_training(pipeline=pipeline, iteration_budget=budget, user_id=request.user.id)
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
                response=AutoresearchRunSerializer(many=True),
                description=(
                    "One AutoresearchRun per matured prediction date that was validated. "
                    "Empty list when no prediction dates have matured yet."
                ),
            ),
            400: OpenApiResponse(description="Pipeline is archived."),
        },
        summary="Run online validation",
        description=(
            "Validate predictions against realized outcomes for all matured prediction dates. "
            "A prediction date is matured when today >= prediction_date + horizon_days. "
            "Computes realized AUC, Brier score, calibration error (ECE), and lift@10/20 per model. "
            "Updates the model's realized_score, calibration_error, and clears the is_preliminary flag. "
            "Already-validated dates are skipped. In production this is triggered by the daily "
            "Temporal validation workflow after inference runs."
        ),
    )
    @action(detail=True, methods=["post"], url_path="validate-online")
    def run_validation(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        pipeline = self.get_object()
        if pipeline.status == AutoresearchPipeline.Status.ARCHIVED:
            raise ValidationError("Cannot validate an archived pipeline.")

        runs = run_online_validation_for_pipeline(pipeline=pipeline)
        return Response(AutoresearchRunSerializer(runs, many=True).data)

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

    scope_object = "autoresearch"
    permission_classes = [AutoresearchAccessPermission]
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

    scope_object = "autoresearch"
    permission_classes = [AutoresearchAccessPermission]
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

    scope_object = "autoresearch"
    permission_classes = [AutoresearchAccessPermission]
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


@extend_schema(tags=["autoresearch"])
class AutoresearchSuggestionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    Submit and list steering suggestions for a running pipeline.

    A suggestion is a free-text hypothesis or direction injected by a user or agent.
    At the start of the next training batch the sandbox agent reads pending suggestions
    and decides whether to translate each into a concrete iteration, apply it as a
    search constraint, or dismiss it with rationale.
    """

    scope_object = "autoresearch"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["create"]
    permission_classes = [AutoresearchAccessPermission]
    serializer_class = AutoresearchSuggestionSerializer
    queryset = AutoresearchSuggestion.objects.all()

    def _should_skip_parents_filter(self) -> bool:
        return True

    def safely_get_queryset(self, queryset: Any) -> Any:
        pipeline_id = self.kwargs.get("parent_lookup_pipeline_id")
        qs = queryset.filter(pipeline__team=self.team).select_related("pipeline", "created_by")
        if pipeline_id:
            qs = qs.filter(pipeline_id=pipeline_id)
        return qs.order_by("-created_at")

    @extend_schema(
        responses={200: AutoresearchSuggestionSerializer(many=True)},
        summary="List suggestions",
        description=(
            "List steering suggestions for a pipeline, ordered most recent first. "
            "Check 'status' to see which have been picked up or acted on by the agent."
        ),
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        qs = self.safely_get_queryset(self.get_queryset())
        serializer = AutoresearchSuggestionSerializer(qs, many=True)
        return Response(serializer.data)

    @extend_schema(
        responses={200: AutoresearchSuggestionSerializer},
        summary="Get suggestion",
        description="Get details for a specific suggestion including its status and agent_response.",
    )
    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        return Response(AutoresearchSuggestionSerializer(instance).data)

    @validated_request(
        request_serializer=CreateSuggestionSerializer,
        responses={
            201: OpenApiResponse(
                response=AutoresearchSuggestionSerializer,
                description="The created suggestion. The agent will pick it up at the start of the next training batch.",
            ),
        },
        summary="Submit a suggestion",
        description=(
            "Inject a free-text hypothesis or direction into a running pipeline. "
            "The sandbox agent reads queued suggestions at the start of each iteration batch and decides: "
            "translate into a concrete iteration ('acted_on'), apply as a search constraint ('picked_up'), "
            "or reject with rationale ('dismissed'). "
            "Use priority='try_next' to instruct the agent to act on this before autonomous iterations; "
            "'consider' is advisory. "
            "Check 'agent_response' after the next training run to see how the suggestion was interpreted."
        ),
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        pipeline_id = self.kwargs.get("parent_lookup_pipeline_id")
        try:
            pipeline = AutoresearchPipeline.objects.get(pk=pipeline_id, team=self.team)
        except AutoresearchPipeline.DoesNotExist:
            raise ValidationError("Pipeline not found.")

        if pipeline.status == AutoresearchPipeline.Status.ARCHIVED:
            raise ValidationError("Cannot submit suggestions to an archived pipeline.")

        data = request.validated_data  # type: ignore[attr-defined]
        suggestion = AutoresearchSuggestion.objects.create(
            pipeline=pipeline,
            created_by=request.user,
            prompt=data["prompt"],
            priority=data.get("priority", AutoresearchSuggestion.Priority.CONSIDER),
            source=AutoresearchSuggestion.Source.USER,
        )
        return Response(AutoresearchSuggestionSerializer(suggestion).data, status=201)
