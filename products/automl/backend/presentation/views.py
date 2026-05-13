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
from ..facade.contracts import CreatePipelineInput, UpdatePipelineInput
from .serializers import AutoMLPipelineSerializer, CreatePipelineInputSerializer, UpdatePipelineInputSerializer

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
    scope_object_write_actions = ["create", "partial_update", "start", "pause", "resume", "archive"]
    scope_object_read_actions = ["list", "retrieve"]
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
