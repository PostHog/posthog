"""
DRF views for AutoML.

Responsibilities:
- Validate incoming JSON (via serializers).
- Convert JSON to DTOs.
- Call facade methods (``backend/facade/api.py``).
- Convert DTOs to JSON responses.

No business logic — that belongs in ``logic/`` via the facade.
"""

from typing import cast
from uuid import UUID

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import TypedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api
from ..facade.contracts import (
    CreatePipelineInput,
    RecordBootstrapOutcomeInput,
    RecordEdaResultInput,
    RecordTrainingResultInput,
    UpdatePipelineInput,
)
from ..facade.enums import ModelRole
from .serializers import (
    AutoMLModelVersionSerializer,
    AutoMLPipelineRunSerializer,
    AutoMLPipelineSerializer,
    CreatePipelineInputSerializer,
    RecordBootstrapOutcomeInputSerializer,
    RecordEdaResultInputSerializer,
    RecordTrainingResultInputSerializer,
    UpdatePipelineInputSerializer,
    ValidationReportSerializer,
)

AUTOML_TAG = "automl"


@extend_schema(tags=[AUTOML_TAG])
class AutoMLPipelineViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    AutoML pipelines.

    A pipeline captures the user-configured surface of an AutoML task: target,
    populations, cadence, autonomy, and lifecycle status. Status transitions
    flow through the dedicated start / pause / resume / archive actions so the
    state machine stays explicit.
    """

    scope_object = "automl"
    scope_object_write_actions = [
        "create",
        "partial_update",
        "start",
        "pause",
        "resume",
        "archive",
        "record_model_version",
        "promote_model_version",
        "record_eda_result",
        "record_bootstrap_outcome",
    ]
    scope_object_read_actions = [
        "list",
        "retrieve",
        "validate",
        "list_model_versions",
        "active_model_version",
        "list_runs",
        "retrieve_run",
    ]
    serializer_class = AutoMLPipelineSerializer

    @extend_schema(responses={200: AutoMLPipelineSerializer(many=True)})
    def list(self, request: Request, **kwargs) -> Response:
        """List non-archived pipelines for the team, newest first."""
        pipelines = api.list_for_team(team_id=self.team_id)
        page = self.paginate_queryset(pipelines)
        if page is not None:
            serializer = AutoMLPipelineSerializer(instance=page, many=True)
            return self.get_paginated_response(serializer.data)
        return Response(AutoMLPipelineSerializer(instance=pipelines, many=True).data)

    @validated_request(
        request_serializer=CreatePipelineInputSerializer,
        responses={201: OpenApiResponse(response=AutoMLPipelineSerializer)},
    )
    def create(self, request: TypedRequest[CreatePipelineInput], **kwargs) -> Response:
        """Create a new pipeline in draft state."""
        dto = api.create(
            team_id=self.team_id,
            params=request.validated_data,
            created_by_id=cast(int | None, getattr(request.user, "id", None)),
        )
        return Response(AutoMLPipelineSerializer(instance=dto).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        parameters=[OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH)],
        responses={200: AutoMLPipelineSerializer},
    )
    def retrieve(self, request: Request, pk: str, **kwargs) -> Response:
        """Get one pipeline by ID."""
        dto = api.get(team_id=self.team_id, pipeline_id=UUID(pk))
        if dto is None:
            return Response({"detail": "Pipeline not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(AutoMLPipelineSerializer(instance=dto).data)

    @extend_schema(parameters=[OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH)])
    @validated_request(
        request_serializer=UpdatePipelineInputSerializer,
        responses={200: OpenApiResponse(response=AutoMLPipelineSerializer)},
    )
    def partial_update(self, request: TypedRequest[UpdatePipelineInput], pk: str, **kwargs) -> Response:
        """Apply partial config updates. Use start / pause / resume / archive for status transitions."""
        dto = api.update(team_id=self.team_id, pipeline_id=UUID(pk), params=request.validated_data)
        if dto is None:
            return Response({"detail": "Pipeline not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(AutoMLPipelineSerializer(instance=dto).data)

    @extend_schema(
        parameters=[OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH)],
        request=None,
        responses={200: AutoMLPipelineSerializer},
    )
    @action(detail=True, methods=["post"])
    def start(self, request: Request, pk: str, **kwargs) -> Response:
        """Transition a draft pipeline to bootstrap-pending and enqueue the first training run.

        The training itself runs in a sandbox via the ``tasks`` product (one
        Task per pipeline bootstrap). The task id lands on the pipeline as
        ``runtime.bootstrap_task_id`` so the agent's progress is traceable.
        """
        user_id = cast(int | None, getattr(request.user, "id", None))
        if user_id is None:
            return Response(
                {"detail": "Authentication required to start a pipeline."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            dto = api.start(team_id=self.team_id, pipeline_id=UUID(pk), user_id=user_id)
        except api.PipelineNotFoundError:
            return Response({"detail": "Pipeline not found"}, status=status.HTTP_404_NOT_FOUND)
        except api.PipelineStateTransitionError as e:
            return Response(
                {"detail": str(e), "code": "invalid_transition"},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(AutoMLPipelineSerializer(instance=dto).data)

    @extend_schema(
        parameters=[OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH)],
        request=None,
        responses={200: AutoMLPipelineSerializer},
    )
    @action(detail=True, methods=["post"])
    def pause(self, request: Request, pk: str, **kwargs) -> Response:
        """Pause scheduled inference / training for the pipeline."""
        return self._run_transition(pk, "pause")

    @extend_schema(
        parameters=[OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH)],
        request=None,
        responses={200: AutoMLPipelineSerializer},
    )
    @action(detail=True, methods=["post"])
    def resume(self, request: Request, pk: str, **kwargs) -> Response:
        """Resume a paused pipeline."""
        return self._run_transition(pk, "resume")

    @extend_schema(
        parameters=[OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH)],
        request=None,
        responses={200: AutoMLPipelineSerializer},
    )
    @action(detail=True, methods=["post"])
    def archive(self, request: Request, pk: str, **kwargs) -> Response:
        """Soft-archive a pipeline. Inference stops; history is preserved."""
        return self._run_transition(pk, "archive")

    @validated_request(
        request_serializer=CreatePipelineInputSerializer,
        responses={200: OpenApiResponse(response=ValidationReportSerializer)},
    )
    @action(detail=False, methods=["post"])
    def validate(self, request: TypedRequest[CreatePipelineInput], **kwargs) -> Response:
        """Run preflight validation against a proposed pipeline config.

        Side-effect-free: nothing is written, no pipeline is created. Same body
        shape as the create endpoint; call this first so the user can see the
        validation report (volume, base rate, leakage warnings, sample plan)
        before committing to a pipeline.
        """
        report = api.validate(team_id=self.team_id, params=request.validated_data)
        return Response(ValidationReportSerializer(instance=report).data)

    @extend_schema(
        parameters=[OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH)],
        responses={200: AutoMLModelVersionSerializer(many=True)},
    )
    @action(detail=True, methods=["get"], url_path="model_versions")
    def list_model_versions(self, request: Request, pk: str, **kwargs) -> Response:
        """List every trained model version on a pipeline, newest first.

        Archived versions are included — they're the audit trail and the
        ``$model_version_id`` on past prediction events still needs to resolve.
        """
        try:
            versions = api.list_model_versions(team_id=self.team_id, pipeline_id=UUID(pk))
        except api.PipelineNotFoundError:
            return Response({"detail": "Pipeline not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(AutoMLModelVersionSerializer(instance=versions, many=True).data)

    @extend_schema(parameters=[OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH)])
    @validated_request(
        request_serializer=RecordTrainingResultInputSerializer,
        responses={201: OpenApiResponse(response=AutoMLModelVersionSerializer)},
    )
    @list_model_versions.mapping.post
    def record_model_version(self, request: TypedRequest[RecordTrainingResultInput], pk: str, **kwargs) -> Response:
        """Persist a completed training run as a new model version.

        Always recorded as ``challenger`` by default — promotion to champion is
        the explicit ``promote`` action below. Called by the bootstrap and
        retraining agents from inside their sandbox after the trainer returns.
        """
        try:
            dto = api.record_training_result(
                team_id=self.team_id,
                pipeline_id=UUID(pk),
                params=request.validated_data,
            )
        except api.PipelineNotFoundError:
            return Response({"detail": "Pipeline not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(AutoMLModelVersionSerializer(instance=dto).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        parameters=[
            OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH),
            OpenApiParameter(
                "role",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="Role to look up. Defaults to 'champion'. One of: champion, challenger, archived.",
                required=False,
            ),
        ],
        responses={200: AutoMLModelVersionSerializer},
    )
    @action(detail=True, methods=["get"], url_path="model_versions/active")
    def active_model_version(self, request: Request, pk: str, **kwargs) -> Response:
        """Get the model version currently holding a role on a pipeline.

        The partial unique constraint guarantees at most one champion and one
        challenger per pipeline. Returns 404 when no version holds the role —
        the most common cause is a pipeline that hasn't completed bootstrap yet.
        """
        raw_role = request.query_params.get("role", ModelRole.CHAMPION.value)
        try:
            role = ModelRole(raw_role)
        except ValueError:
            return Response(
                {"detail": f"Unknown role: {raw_role}", "code": "invalid_role"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            dto = api.get_active_model(team_id=self.team_id, pipeline_id=UUID(pk), role=role)
        except api.PipelineNotFoundError:
            return Response({"detail": "Pipeline not found"}, status=status.HTTP_404_NOT_FOUND)
        if dto is None:
            return Response(
                {"detail": f"No model version holds role '{role.value}' on this pipeline."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(AutoMLModelVersionSerializer(instance=dto).data)

    @extend_schema(
        parameters=[
            OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH),
            OpenApiParameter("version_id", OpenApiTypes.STR, OpenApiParameter.PATH),
        ],
        request=None,
        responses={200: AutoMLModelVersionSerializer},
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=r"model_versions/(?P<version_id>[^/.]+)/promote",
    )
    def promote_model_version(self, request: Request, pk: str, version_id: str, **kwargs) -> Response:
        """Make ``version_id`` the champion for its pipeline.

        Atomic: the prior champion (if any) is archived in the same transaction
        the target is set to champion. Idempotent — promoting an existing
        champion is a no-op. Returns 404 if the version doesn't belong to the
        team or pipeline.
        """
        try:
            target_uuid = UUID(version_id)
        except ValueError:
            return Response(
                {"detail": "Invalid version_id", "code": "invalid_version_id"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            dto = api.promote_to_champion(team_id=self.team_id, model_version_id=target_uuid)
        except api.ModelVersionNotFoundError:
            return Response({"detail": "Model version not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(AutoMLModelVersionSerializer(instance=dto).data)

    @extend_schema(
        parameters=[OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH)],
        responses={200: AutoMLPipelineRunSerializer(many=True)},
    )
    @action(detail=True, methods=["get"], url_path="runs")
    def list_runs(self, request: Request, pk: str, **kwargs) -> Response:
        """List every run (bootstrap / retrain / inference) for a pipeline, newest first.

        Includes terminal runs (succeeded / failed / aborted) — the pipeline-detail
        timeline surfaces the full history. Returns 200 with an empty list if the
        pipeline has no runs yet (e.g. before ``start`` is called for the first time).
        """
        try:
            runs = api.list_runs_for_pipeline(team_id=self.team_id, pipeline_id=UUID(pk))
        except api.PipelineNotFoundError:
            return Response({"detail": "Pipeline not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(AutoMLPipelineRunSerializer(instance=runs, many=True).data)

    @extend_schema(
        parameters=[
            OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH),
            OpenApiParameter("run_id", OpenApiTypes.STR, OpenApiParameter.PATH),
        ],
        responses={200: AutoMLPipelineRunSerializer},
    )
    @action(detail=True, methods=["get"], url_path=r"runs/(?P<run_id>[^/.]+)")
    def retrieve_run(self, request: Request, pk: str, run_id: str, **kwargs) -> Response:
        """Get one pipeline run by id.

        Used by the bootstrap agent to look up its own run mid-flight (e.g. to
        confirm a previous ``record_eda_result`` write landed before continuing).
        """
        try:
            run_uuid = UUID(run_id)
        except ValueError:
            return Response(
                {"detail": "Invalid run_id", "code": "invalid_run_id"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        dto = api.get_run(team_id=self.team_id, run_id=run_uuid)
        if dto is None:
            return Response({"detail": "Run not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(AutoMLPipelineRunSerializer(instance=dto).data)

    @extend_schema(
        parameters=[
            OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH),
            OpenApiParameter("run_id", OpenApiTypes.STR, OpenApiParameter.PATH),
        ],
    )
    @validated_request(
        request_serializer=RecordEdaResultInputSerializer,
        responses={200: OpenApiResponse(response=AutoMLPipelineRunSerializer)},
    )
    @action(detail=True, methods=["post"], url_path=r"runs/(?P<run_id>[^/.]+)/record_eda_result")
    def record_eda_result(
        self,
        request: TypedRequest[RecordEdaResultInput],
        pk: str,
        run_id: str,
        **kwargs,
    ) -> Response:
        """Stash the agent's EDA output on an in-progress run.

        Called by the bootstrap agent between ``automl eda`` and ``automl train``.
        Status stays at ``running`` — EDA is a mid-run checkpoint, not terminal.
        Idempotent in the sense that a second call overwrites the prior payload
        (the CLI's ``eda.yaml`` is regenerated on every re-run).
        """
        try:
            run_uuid = UUID(run_id)
        except ValueError:
            return Response(
                {"detail": "Invalid run_id", "code": "invalid_run_id"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            dto = api.record_eda_result(
                team_id=self.team_id,
                run_id=run_uuid,
                params=request.validated_data,
            )
        except api.PipelineRunNotFoundError:
            return Response({"detail": "Run not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(AutoMLPipelineRunSerializer(instance=dto).data)

    @extend_schema(
        parameters=[
            OpenApiParameter("id", OpenApiTypes.STR, OpenApiParameter.PATH),
            OpenApiParameter("run_id", OpenApiTypes.STR, OpenApiParameter.PATH),
        ],
    )
    @validated_request(
        request_serializer=RecordBootstrapOutcomeInputSerializer,
        responses={200: OpenApiResponse(response=AutoMLPipelineRunSerializer)},
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=r"runs/(?P<run_id>[^/.]+)/record_bootstrap_outcome",
    )
    def record_bootstrap_outcome(
        self,
        request: TypedRequest[RecordBootstrapOutcomeInput],
        pk: str,
        run_id: str,
        **kwargs,
    ) -> Response:
        """Flip a run to a terminal state and write the agent's final outcome report.

        Single-shot — once a run reaches a terminal state, re-calling this no-ops
        (returns the already-terminal DTO). Lets the agent retry the MCP call
        after a transient network blip without overwriting the timeline.
        Rejects ``status='running'`` with 400 (terminal status required).
        """
        try:
            run_uuid = UUID(run_id)
        except ValueError:
            return Response(
                {"detail": "Invalid run_id", "code": "invalid_run_id"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            dto = api.record_bootstrap_outcome(
                team_id=self.team_id,
                run_id=run_uuid,
                params=request.validated_data,
            )
        except api.PipelineRunNotFoundError:
            return Response({"detail": "Run not found"}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response(
                {"detail": str(e), "code": "invalid_status"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(AutoMLPipelineRunSerializer(instance=dto).data)

    def _run_transition(self, pk: str, transition: str) -> Response:
        """Dispatch a status transition. Maps facade exceptions to HTTP responses."""
        try:
            method = getattr(api, transition)
            dto = method(team_id=self.team_id, pipeline_id=UUID(pk))
        except api.PipelineNotFoundError:
            return Response({"detail": "Pipeline not found"}, status=status.HTTP_404_NOT_FOUND)
        except api.PipelineStateTransitionError as e:
            return Response(
                {"detail": str(e), "code": "invalid_transition"},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(AutoMLPipelineSerializer(instance=dto).data)
