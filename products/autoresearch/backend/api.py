import json
import base64
import hashlib
import binascii
from typing import Any

from django.utils import timezone as django_timezone

import structlog
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from products.autoresearch.backend import artifacts as artifact_store
from products.autoresearch.backend.access import has_autoresearch_access
from products.autoresearch.backend.inference import run_inference_for_pipeline
from products.autoresearch.backend.models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchRun,
    AutoresearchSuggestion,
    AutoresearchTrainingRun,
)
from products.autoresearch.backend.online_validation import run_online_validation_for_pipeline
from products.autoresearch.backend.promotion import complete_training_run
from products.autoresearch.backend.recipe_validation import RecipeValidationError, validate_feature_sql
from products.autoresearch.backend.sandbox_inference import (
    SandboxInferenceError,
    features_parquet,
    labels_parquet,
    materialize_training_data,
)
from products.autoresearch.backend.serializers import (
    ArtifactContentSerializer,
    ArtifactDeleteResultSerializer,
    ArtifactListSerializer,
    ArtifactPathSerializer,
    ArtifactUploadSerializer,
    AutoresearchIterationSerializer,
    AutoresearchModelSerializer,
    AutoresearchPipelineCreateSerializer,
    AutoresearchPipelineSerializer,
    AutoresearchRunSerializer,
    AutoresearchSuggestionSerializer,
    AutoresearchTrainingRunSerializer,
    CompleteTrainingRunSerializer,
    CreateSuggestionSerializer,
    MaterializeFeaturesRequestSerializer,
    MaterializeFeaturesResponseSerializer,
    OpenTrainingRunSerializer,
    RecordIterationSerializer,
    ResolvedTemplateSerializer,
    ResolveTemplateRequestSerializer,
    RespondToSuggestionSerializer,
    StartTrainingRequestSerializer,
    StoredArtifactSerializer,
    TemplateInfoSerializer,
    TrainingRunHistorySerializer,
    ValidatePipelineRequestSerializer,
    ValidatePipelineResponseSerializer,
    resolve_target,
)
from products.autoresearch.backend.templates import (
    TEMPLATES,
    resolve_template as resolve_template_def,
)
from products.autoresearch.backend.training import run_training
from products.autoresearch.backend.validation import validate_pipeline_definition
from products.tasks.backend.facade.sandbox import get_sandbox_class

logger = structlog.get_logger(__name__)

# Where materialized training parquet lands inside the agent's sandbox. The agent reads
# these paths with pd.read_parquet — the rows never transit the model's context.
_AGENT_FEATURE_DIR = "/tmp/workspace/autoresearch/data"


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
                    "Resolved pipeline config. Pass target_event, horizon_days, "
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
        target_event, target_definition = resolve_target(
            team=self.team,
            target_event=data.get("target_event", ""),
            target_definition=data.get("target_definition"),
        )
        result = validate_pipeline_definition(
            team=self.team,
            target_event=target_event,
            target_definition=target_definition,
            horizon_days=data.get("horizon_days", 7),
            training_lookback_days=data.get("training_lookback_days", 180),
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
class AutoresearchTrainingRunViewSet(TeamAndOrgViewSetMixin, mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    """
    List, retrieve, open, record iterations into, and complete training runs for a pipeline.

    The write endpoints let an external (bring-your-own) agent or a scheduled job drive a
    training run directly — recording each iteration as it completes rather than via a single
    terminal sandbox output. Recipe validation and champion promotion stay server-side.
    """

    scope_object = "autoresearch"
    scope_object_read_actions = ["list", "retrieve", "list_artifacts", "get_artifact", "history"]
    scope_object_write_actions = [
        "create",
        "record_iteration",
        "complete",
        "materialize_features",
        "upload_artifact",
        "delete_artifact",
    ]
    permission_classes = [AutoresearchAccessPermission]
    serializer_class = AutoresearchTrainingRunSerializer
    queryset = AutoresearchTrainingRun.objects.all()

    def _should_skip_parents_filter(self) -> bool:
        return True

    def safely_get_queryset(self, queryset: Any) -> Any:
        pipeline_id = self.kwargs.get("parent_lookup_pipeline_id")
        qs = queryset.filter(pipeline__team=self.team).select_related("pipeline").prefetch_related("iterations")
        if pipeline_id:
            qs = qs.filter(pipeline_id=pipeline_id)
        return qs.order_by("-created_at")

    def _get_pipeline(self) -> AutoresearchPipeline:
        pipeline_id = self.kwargs.get("parent_lookup_pipeline_id")
        try:
            return AutoresearchPipeline.objects.get(pk=pipeline_id, team=self.team)
        except AutoresearchPipeline.DoesNotExist:
            raise ValidationError("Pipeline not found.")

    @validated_request(
        request_serializer=OpenTrainingRunSerializer,
        responses={
            201: OpenApiResponse(
                response=AutoresearchTrainingRunSerializer,
                description="The opened training run. Record iterations against its id, then call complete.",
            ),
            400: OpenApiResponse(description="Pipeline is archived."),
        },
        summary="Open a training run",
        description=(
            "Open a new training run for a pipeline and return its id. An agent — the in-house sandbox, an "
            "external bring-your-own agent, or a scheduled job — then records iterations against this run "
            "and finalizes it with the complete endpoint. The run starts in 'running'."
        ),
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        pipeline = self._get_pipeline()
        if pipeline.status == AutoresearchPipeline.Status.ARCHIVED:
            raise ValidationError("Cannot open a training run on an archived pipeline.")
        data = request.validated_data  # type: ignore[attr-defined]
        training_run = AutoresearchTrainingRun.objects.create(
            pipeline=pipeline,
            status=AutoresearchTrainingRun.Status.RUNNING,
            iteration_budget=data.get("iteration_budget") or pipeline.iteration_budget,
            started_at=django_timezone.now(),
        )
        return Response(AutoresearchTrainingRunSerializer(training_run).data, status=201)

    @validated_request(
        request_serializer=RecordIterationSerializer,
        responses={
            201: OpenApiResponse(
                response=AutoresearchIterationSerializer,
                description="The recorded iteration.",
            ),
            400: OpenApiResponse(
                description="Recipe failed validation (e.g. disallowed model_class) or run not running."
            ),
        },
        summary="Record a training iteration",
        description=(
            "Record one iteration of an open training run. Idempotent on iteration_number — re-sending the "
            "same number updates that iteration. The recipe is validated server-side: model_class must be in "
            "the allowlist and feature_sql must be a read-only SELECT keyed on person_id."
        ),
    )
    @action(detail=True, methods=["post"], url_path="iterations")
    def record_iteration(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        training_run = self.get_object()
        if training_run.status != AutoresearchTrainingRun.Status.RUNNING:
            raise ValidationError("Can only record iterations on a running training run.")
        data = request.validated_data  # type: ignore[attr-defined]
        recipe_snapshot = data["recipe_snapshot"]
        model_spec = data["model_spec"]
        recipe_hash = hashlib.sha256(
            json.dumps({"recipe": recipe_snapshot, "spec": model_spec}, sort_keys=True).encode()
        ).hexdigest()

        # Link the iteration to the suggestion that spawned it, if any. Scope the lookup to this
        # run's pipeline so a foreign suggestion id can't be attached across tenants.
        parent_suggestion = None
        parent_suggestion_id = data.get("parent_suggestion")
        if parent_suggestion_id:
            try:
                parent_suggestion = AutoresearchSuggestion.objects.get(
                    id=parent_suggestion_id, pipeline=training_run.pipeline
                )
            except AutoresearchSuggestion.DoesNotExist:
                raise ValidationError("parent_suggestion not found on this pipeline.")

        iteration, _ = AutoresearchIteration.objects.update_or_create(
            training_run=training_run,
            iteration_number=data["iteration_number"],
            defaults={
                "pipeline": training_run.pipeline,
                "recipe_hash": recipe_hash,
                "recipe_snapshot": recipe_snapshot,
                "model_spec": model_spec,
                "train_score": data.get("train_score"),
                "holdout_score": data.get("holdout_score"),
                "status": data["status"],
                "agent_description": data.get("agent_description", ""),
                "agent_confidence": data.get("agent_confidence"),
                "parent_suggestion": parent_suggestion,
            },
        )

        # Spawning an iteration from a suggestion is itself acting on it — advance the suggestion so
        # the UI reflects the pickup even if the agent never calls the respond endpoint.
        if parent_suggestion and parent_suggestion.status in (
            AutoresearchSuggestion.Status.QUEUED,
            AutoresearchSuggestion.Status.PICKED_UP,
        ):
            parent_suggestion.status = AutoresearchSuggestion.Status.ACTED_ON
            parent_suggestion.save(update_fields=["status", "updated_at"])

        return Response(AutoresearchIterationSerializer(iteration).data, status=201)

    @validated_request(
        request_serializer=MaterializeFeaturesRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=MaterializeFeaturesResponseSerializer,
                description="Sandbox paths to the train/holdout feature and label parquet files, plus row counts and feature columns.",
            ),
            400: OpenApiResponse(
                description="Run not running, features_sql invalid, sandbox unavailable, or the query produced no usable rows."
            ),
        },
        summary="Materialize training features to the sandbox",
        description=(
            "Run features_sql server-side against the labeled training population and write the resulting "
            "train/holdout feature and label parquet files directly into this run's sandbox. Returns the local "
            "sandbox paths, row counts, and feature columns. The rows never pass through the agent's context and "
            "there is no 500-row cap. Read the returned paths with pd.read_parquet and iterate in Python."
        ),
    )
    @action(detail=True, methods=["post"], url_path="materialize-features")
    def materialize_features(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        training_run = self.get_object()
        if training_run.status != AutoresearchTrainingRun.Status.RUNNING:
            raise ValidationError("Can only materialize features for a running training run.")
        features_sql = request.validated_data["features_sql"]  # type: ignore[attr-defined]
        try:
            validate_feature_sql(features_sql)
        except RecipeValidationError as exc:
            raise ValidationError(str(exc))

        sandbox_id = self._resolve_run_sandbox_id(training_run)
        try:
            data = materialize_training_data(team=self.team, pipeline=training_run.pipeline, feature_sql=features_sql)
        except SandboxInferenceError as exc:
            raise ValidationError(f"Feature materialization failed: {exc}")
        if not data.train_rows:
            raise ValidationError("features_sql produced no training rows.")
        if not data.feature_cols:
            raise ValidationError("features_sql produced no numeric feature columns.")

        paths = self._write_feature_parquets(sandbox_id, data)
        response = {
            **paths,
            "n_train": len(data.train_rows),
            "n_holdout": len(data.holdout_rows),
            "n_features": len(data.feature_cols),
            "feature_cols": data.feature_cols,
        }
        logger.info(
            "autoresearch_features_materialized_to_sandbox",
            pipeline_id=str(training_run.pipeline_id),
            training_run_id=str(training_run.id),
            n_train=len(data.train_rows),
            n_holdout=len(data.holdout_rows),
            n_features=len(data.feature_cols),
        )
        return Response(MaterializeFeaturesResponseSerializer(response).data)

    def _resolve_run_sandbox_id(self, training_run: AutoresearchTrainingRun) -> str:
        """
        Resolve the live sandbox for this training run from its TaskRun state.

        The sandbox id is derived from the team-scoped run record — never from the
        client — and verified to belong to this training run. Raises ValidationError
        if the run has no live sandbox.
        """
        # Deferred to avoid a tasks<->autoresearch import cycle (matches training.run_training).
        from products.tasks.backend.models import TaskRun  # noqa: PLC0415

        if not training_run.task_run_id:
            raise ValidationError("This training run has no sandbox (e.g. a stub run). Cannot materialize features.")
        try:
            task_run = TaskRun.objects.get(id=training_run.task_run_id)
        except TaskRun.DoesNotExist:
            raise ValidationError("Sandbox task run not found for this training run.")
        state = task_run.state or {}
        if str(state.get("autoresearch_training_run_id")) != str(training_run.id):
            raise ValidationError("Sandbox does not belong to this training run.")
        sandbox_id = state.get("sandbox_id")
        if not sandbox_id:
            raise ValidationError("Sandbox is not ready yet — try again once the agent has started.")
        return str(sandbox_id)

    def _write_feature_parquets(self, sandbox_id: str, data: Any) -> dict[str, str]:
        """Serialize train/holdout matrices to parquet and write them into the agent's sandbox."""
        try:
            sandbox = get_sandbox_class().get_by_id(sandbox_id)
        except Exception as exc:
            raise ValidationError(f"Could not connect to the run's sandbox: {exc}")
        # Paths are hardcoded by the framework — the agent supplies the query, never the destination.
        files = {
            "train_features_path": (
                f"{_AGENT_FEATURE_DIR}/train_features.parquet",
                features_parquet(data.train_rows, data.feature_cols),
            ),
            "train_labels_path": (f"{_AGENT_FEATURE_DIR}/train_labels.parquet", labels_parquet(data.train_rows)),
            "holdout_features_path": (
                f"{_AGENT_FEATURE_DIR}/holdout_features.parquet",
                features_parquet(data.holdout_rows, data.feature_cols),
            ),
            "holdout_labels_path": (
                f"{_AGENT_FEATURE_DIR}/holdout_labels.parquet",
                labels_parquet(data.holdout_rows),
            ),
        }
        paths: dict[str, str] = {}
        for key, (path, content) in files.items():
            result = sandbox.write_file(path, content)
            if result.exit_code != 0:
                raise ValidationError(f"Failed to write {path} into the sandbox: {result.stderr[:300]}")
            paths[key] = path
        return paths

    @validated_request(
        request_serializer=CompleteTrainingRunSerializer,
        responses={
            200: OpenApiResponse(
                response=AutoresearchTrainingRunSerializer,
                description="The completed training run. Call autoresearch-models-list to see the resulting champion/challenger.",
            ),
            400: OpenApiResponse(description="Run is already completed or failed."),
        },
        summary="Complete a training run",
        description=(
            "Finalize a training run. The backend selects the best iteration (highest holdout score, or the "
            "one you name), decides champion vs challenger via the promotion ladder, and persists the model. "
            "Agents cannot set the champion directly — promotion is server-side."
        ),
    )
    @action(detail=True, methods=["post"], url_path="complete")
    def complete(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        training_run = self.get_object()
        if training_run.status not in (
            AutoresearchTrainingRun.Status.RUNNING,
            AutoresearchTrainingRun.Status.PENDING,
        ):
            raise ValidationError("Training run is already completed or failed.")
        data = request.validated_data  # type: ignore[attr-defined]
        complete_training_run(
            training_run,
            best_iteration_id=data.get("best_iteration_id"),
            model_explanation=data.get("model_explanation") or {},
            recommended_next=data.get("recommended_next") or "",
            distillation=data.get("distillation") or "",
        )
        training_run.refresh_from_db()
        return Response(AutoresearchTrainingRunSerializer(training_run).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="limit",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum number of prior runs to return (default 5, capped at 20).",
            )
        ],
        responses={
            200: OpenApiResponse(
                response=TrainingRunHistorySerializer,
                description="Prior completed training runs with their iteration trails, for orienting a new run.",
            )
        },
        summary="Read prior training-run history",
        description=(
            "Return recent completed training runs and their iteration trails so a new run can learn "
            "from what was already tried. Scoped to this pipeline first, then same-target sibling "
            "pipelines on the team. Read this before iterating to reuse winning features and avoid "
            "repeating discarded approaches."
        ),
    )
    @action(detail=False, methods=["get"], url_path="history", pagination_class=None)
    def history(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        pipeline = self._get_pipeline()
        try:
            limit = int(request.query_params.get("limit", 5))
        except (TypeError, ValueError):
            limit = 5
        limit = max(1, min(limit, 20))

        completed = (
            AutoresearchTrainingRun.objects.filter(
                status=AutoresearchTrainingRun.Status.COMPLETED,
                pipeline__team=self.team,
            )
            .select_related("pipeline")
            .prefetch_related("iterations")
        )

        # This pipeline's own history first; backfill with same-target sibling pipelines on the team.
        runs = list(completed.filter(pipeline=pipeline).order_by("-completed_at")[:limit])
        remaining = limit - len(runs)
        if remaining > 0:
            runs += list(
                completed.filter(pipeline__target_event=pipeline.target_event)
                .exclude(pipeline=pipeline)
                .order_by("-completed_at")[:remaining]
            )

        entries = [
            {
                "run_id": run.id,
                "pipeline_id": run.pipeline_id,
                "is_current_pipeline": run.pipeline_id == pipeline.id,
                "target_event": run.pipeline.target_event,
                "horizon_days": run.pipeline.horizon_days,
                "best_holdout_score": run.best_holdout_score,
                "iteration_count": run.iteration_count,
                "completed_at": run.completed_at,
                "summary": run.summary or None,
                "iterations": list(run.iterations.all()),
            }
            for run in runs
        ]
        return Response(TrainingRunHistorySerializer({"runs": entries}).data)

    def _bundle_prefix(self, training_run: AutoresearchTrainingRun) -> str:
        return artifact_store.bundle_prefix(
            team_id=self.team_id,
            pipeline_id=str(training_run.pipeline_id),
            training_run_id=str(training_run.id),
        )

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=ArtifactListSerializer,
                description="The relative paths of every file in this run's artifact bundle.",
            ),
        },
        summary="List artifact bundle files",
        description=(
            "List the files an agent has uploaded for this training run's artifact bundle "
            "(train.py, predict.py, features.sql, and any eda/ notebooks)."
        ),
    )
    @action(detail=True, methods=["get"], url_path="artifacts")
    def list_artifacts(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        training_run = self.get_object()
        paths = artifact_store.list_artifacts(self._bundle_prefix(training_run))
        return Response(ArtifactListSerializer({"paths": paths, "count": len(paths)}).data)

    @validated_request(
        request_serializer=ArtifactUploadSerializer,
        responses={
            201: OpenApiResponse(
                response=StoredArtifactSerializer,
                description="The stored file's path, size, and content hash.",
            ),
            400: OpenApiResponse(description="Invalid path, content is not base64, or file exceeds the size limit."),
        },
        summary="Upload an artifact bundle file",
        description=(
            "Upload one file of this training run's artifact bundle. Send the file contents "
            "base64-encoded in content_base64. Re-uploading the same path overwrites it. "
            "Use this — not curl/set_output — to author train.py, predict.py, and features.sql."
        ),
    )
    @action(detail=True, methods=["post"], url_path="artifacts/upload")
    def upload_artifact(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        training_run = self.get_object()
        data = request.validated_data  # type: ignore[attr-defined]
        try:
            content = base64.b64decode(data["content_base64"], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValidationError("content_base64 is not valid base64.") from exc
        try:
            stored = artifact_store.write_artifact(self._bundle_prefix(training_run), data["path"], content)
        except artifact_store.InvalidArtifactPath as exc:
            raise ValidationError(str(exc)) from exc
        return Response(StoredArtifactSerializer(stored).data, status=201)

    @validated_request(
        request_serializer=ArtifactPathSerializer,
        responses={
            200: OpenApiResponse(
                response=ArtifactContentSerializer,
                description="The file's content, base64-encoded, with its size and hash.",
            ),
            404: OpenApiResponse(description="No file at that path in this run's bundle."),
        },
        summary="Get an artifact bundle file",
        description="Fetch one file from this training run's artifact bundle, base64-encoded.",
    )
    @action(detail=True, methods=["post"], url_path="artifacts/get")
    def get_artifact(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        training_run = self.get_object()
        path = request.validated_data["path"]  # type: ignore[attr-defined]
        try:
            content = artifact_store.read_artifact(self._bundle_prefix(training_run), path)
        except artifact_store.InvalidArtifactPath as exc:
            raise ValidationError(str(exc)) from exc
        except artifact_store.BundleNotFound as exc:
            raise NotFound(str(exc)) from exc
        return Response(
            ArtifactContentSerializer(
                {
                    "path": artifact_store.normalize_artifact_path(path),
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "content_base64": base64.b64encode(content).decode("ascii"),
                }
            ).data
        )

    @validated_request(
        request_serializer=ArtifactPathSerializer,
        responses={
            200: OpenApiResponse(
                response=ArtifactDeleteResultSerializer,
                description="Whether a file existed at that path and was removed.",
            ),
        },
        summary="Delete an artifact bundle file",
        description="Remove one file from this training run's artifact bundle. Idempotent — deleting a missing file is a no-op.",
    )
    @action(detail=True, methods=["post"], url_path="artifacts/delete")
    def delete_artifact(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        training_run = self.get_object()
        path = request.validated_data["path"]  # type: ignore[attr-defined]
        try:
            deleted = artifact_store.delete_artifact(self._bundle_prefix(training_run), path)
            normalized = artifact_store.normalize_artifact_path(path)
        except artifact_store.InvalidArtifactPath as exc:
            raise ValidationError(str(exc)) from exc
        return Response(ArtifactDeleteResultSerializer({"path": normalized, "deleted": deleted}).data)


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
    scope_object_write_actions = ["create", "respond"]
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
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = AutoresearchSuggestionSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
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

    @validated_request(
        request_serializer=RespondToSuggestionSerializer,
        responses={
            200: OpenApiResponse(
                response=AutoresearchSuggestionSerializer,
                description="The updated suggestion with its new status and agent_response.",
            ),
        },
        summary="Respond to a suggestion",
        description=(
            "Record how the agent handled a steering suggestion: set status to 'picked_up' (applied as a "
            "search constraint), 'acted_on' (spawned iterations), or 'dismissed' (rejected — explain in "
            "agent_response), and write the agent_response note the human will read. Call this from the "
            "training loop after deciding what to do with a pending suggestion. Recording an iteration with "
            "parent_suggestion set already advances a suggestion to 'acted_on'; use this to add the narrative "
            "or to mark a suggestion picked_up/dismissed without spawning an iteration."
        ),
    )
    @action(detail=True, methods=["post"], url_path="respond")
    def respond(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        suggestion = self.get_object()
        data = request.validated_data  # type: ignore[attr-defined]
        suggestion.status = data["status"]
        if data.get("agent_response"):
            suggestion.agent_response = data["agent_response"]
        suggestion.save(update_fields=["status", "agent_response", "updated_at"])
        return Response(AutoresearchSuggestionSerializer(suggestion).data)
