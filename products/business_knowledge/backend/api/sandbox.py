from functools import cached_property
from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission
from posthog.rate_limit import BurstRateThrottle, SustainedRateThrottle

from products.access_control.backend.facade.user_access_control import UserAccessControl

from ..sandbox import SandboxRunInProgress, load_sandbox_run, start_sandbox_run
from .serializers import SandboxQuestionSerializer, SandboxRunSerializer, SandboxRunStartedSerializer
from .settings import CanonicalTeamTokenPermission


class SandboxConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Wait for the current answer to finish before asking another question."
    default_code = "conflict"


class BusinessKnowledgeSandboxViewSet(TeamAndOrgViewSetMixin, ViewSet):
    scope_object = "business_knowledge"
    # Same gate as settings: resource-level none must not ride a single source grant.
    requires_resource_level_access = True
    serializer_class = SandboxRunSerializer
    permission_classes = [
        IsAuthenticated,
        APIScopePermission,
        PostHogFeatureFlagPermission,
        CanonicalTeamTokenPermission,
    ]
    posthog_feature_flag = "product-business-knowledge"
    throttle_classes = [BurstRateThrottle, SustainedRateThrottle]
    pagination_class = None
    http_method_names = ["get", "post", "head", "options"]

    @cached_property
    def user_access_control(self) -> UserAccessControl:
        team = self.team.parent_team or self.team
        return UserAccessControl(user=cast(User, self.request.user), team=team, organization_id=self.organization_id)

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        if self.action == "retrieve":
            return ["business_knowledge:read"]
        # Asking starts a billable sandbox run, so it needs write like the other mutations.
        if self.action == "create":
            return ["business_knowledge:write"]
        return None

    @extend_schema(
        request=SandboxQuestionSerializer,
        responses={
            201: OpenApiResponse(response=SandboxRunStartedSerializer, description="The sandbox run has started."),
            403: OpenApiResponse(description="AI data processing is not approved for this organization."),
            409: OpenApiResponse(description="This person already has a sandbox run that has not finished."),
        },
        summary="Ask a business knowledge sandbox question",
        description="Start a sandbox agent that can search only this project's business knowledge. Returns immediately.",
    )
    @validated_request(
        request_serializer=SandboxQuestionSerializer,
        responses={201: OpenApiResponse(response=SandboxRunStartedSerializer)},
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        if self.team.organization.is_ai_data_processing_approved is not True:
            raise PermissionDenied("Enable AI data processing before asking another question.")
        try:
            created = start_sandbox_run(
                team=self.team,
                user_id=cast(User, request.user).id,
                question=request.validated_data["question"],
            )
        except SandboxRunInProgress:
            raise SandboxConflict()
        if created.latest_run is None:
            raise RuntimeError("Sandbox task was created without a run")
        return Response(
            SandboxRunStartedSerializer({"task_id": created.task_id, "run_id": created.latest_run.id}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        responses={
            200: OpenApiResponse(response=SandboxRunSerializer, description="Current sandbox run."),
            404: OpenApiResponse(description="No sandbox run with this id for the current user."),
        },
        summary="Get a business knowledge sandbox run",
        description="Poll a sandbox run started by the current user. A run that started before AI data processing was turned off can still be read.",
    )
    def retrieve(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        payload = load_sandbox_run(
            task_id=pk or "",
            team_id=self.team.id,
            user_id=cast(User, request.user).id,
        )
        if payload is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(SandboxRunSerializer(payload).data)
