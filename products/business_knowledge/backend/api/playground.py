from functools import cached_property
from typing import Any, cast

from django.db.models import QuerySet

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission
from posthog.rate_limit import BurstRateThrottle, SustainedRateThrottle

from products.access_control.backend.facade.user_access_control import UserAccessControl

from ..models import PlaygroundChat
from ..playground import (
    ask_playground_chat,
    create_playground_chat,
    serialize_playground_chat,
    serialize_playground_chat_list_item,
)
from ..sandbox import SandboxRunInProgress
from .sandbox import SandboxConflict
from .serializers import PlaygroundChatListSerializer, PlaygroundChatSerializer, SandboxQuestionSerializer
from .settings import CanonicalTeamTokenPermission


class BusinessKnowledgePlaygroundChatViewSet(
    TeamAndOrgViewSetMixin,
    mixins.DestroyModelMixin,
    GenericViewSet,
):
    scope_object = "business_knowledge"
    requires_resource_level_access = True
    queryset = PlaygroundChat.objects.unscoped()
    serializer_class = PlaygroundChatSerializer
    permission_classes = [
        IsAuthenticated,
        APIScopePermission,
        PostHogFeatureFlagPermission,
        CanonicalTeamTokenPermission,
    ]
    posthog_feature_flag = "product-business-knowledge"
    throttle_classes = [BurstRateThrottle, SustainedRateThrottle]
    pagination_class = None
    http_method_names = ["get", "post", "delete", "head", "options"]

    @cached_property
    def user_access_control(self) -> UserAccessControl:
        team = self.team.parent_team or self.team
        return UserAccessControl(user=cast(User, self.request.user), team=team, organization_id=self.organization_id)

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        if self.action in ("list", "create", "retrieve", "destroy", "ask"):
            return ["business_knowledge:read"]
        return None

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(
            team_id=self.team_id,
            created_by_id=cast(User, self.request.user).id,
        ).order_by("-created_at")

    @extend_schema(
        responses={200: PlaygroundChatListSerializer(many=True)},
        summary="List business knowledge playground chats",
        description="Chats started by the current user in this project.",
    )
    def list(self, request: Request, **kwargs: Any) -> Response:
        chats = [serialize_playground_chat_list_item(chat) for chat in self.get_queryset()]
        return Response(PlaygroundChatListSerializer(chats, many=True).data)

    @extend_schema(
        request=None,
        responses={201: OpenApiResponse(response=PlaygroundChatSerializer, description="Empty playground chat.")},
        summary="Create a business knowledge playground chat",
        description="Create an empty chat. The first question sets the title.",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        user = cast(User, request.user)
        chat = create_playground_chat(team=self.team, user=user)
        return Response(
            PlaygroundChatSerializer(serialize_playground_chat(chat=chat, user_id=user.id)).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        responses={
            200: OpenApiResponse(response=PlaygroundChatSerializer, description="Playground chat with turns."),
            404: OpenApiResponse(description="No playground chat with this id for the current user."),
        },
        summary="Get a business knowledge playground chat",
        description="Reload a chat and its turns. Each turn's answer comes from its sandbox run. A chat started before AI data processing was turned off can still be read.",
    )
    def retrieve(self, request: Request, **kwargs: Any) -> Response:
        chat = self.get_object()
        return Response(
            PlaygroundChatSerializer(serialize_playground_chat(chat=chat, user_id=cast(User, request.user).id)).data
        )

    @extend_schema(
        responses={204: OpenApiResponse(description="Chat deleted.")},
        summary="Delete a business knowledge playground chat",
        description="Deletes the chat and its turns. Does not cancel a running sandbox agent.",
    )
    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().destroy(request, *args, **kwargs)

    @extend_schema(
        request=SandboxQuestionSerializer,
        responses={
            201: OpenApiResponse(response=PlaygroundChatSerializer, description="Chat with the new turn."),
            403: OpenApiResponse(description="AI data processing is not approved for this organization."),
            409: OpenApiResponse(description="This person already has a sandbox run that has not finished."),
        },
        summary="Ask a question in a playground chat",
        description="Append a turn and start a sandbox run. A second question while any run is still open returns 409, including from a different chat.",
    )
    @validated_request(
        request_serializer=SandboxQuestionSerializer,
        responses={201: OpenApiResponse(response=PlaygroundChatSerializer)},
    )
    @action(detail=True, methods=["post"], url_path="ask")
    def ask(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        if self.team.organization.is_ai_data_processing_approved is not True:
            raise PermissionDenied("Enable AI data processing before asking another question.")
        chat = self.get_object()
        try:
            payload = ask_playground_chat(
                chat=chat,
                team=self.team,
                user_id=cast(User, request.user).id,
                question=request.validated_data["question"],
            )
        except SandboxRunInProgress:
            raise SandboxConflict()
        return Response(PlaygroundChatSerializer(payload).data, status=status.HTTP_201_CREATED)
