from __future__ import annotations

from typing import Any, cast

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import PostHogAutoSchema
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User

from products.conversations.backend.models import AGENT_SIGNATURE_MAX_CHARS, AgentSignature


class AgentSignatureSerializer(serializers.Serializer):
    text = serializers.CharField(
        allow_blank=True,
        max_length=AGENT_SIGNATURE_MAX_CHARS,
        trim_whitespace=True,
        help_text="Plain-text signature added to the end of support emails you send from this project. Line breaks are kept. Empty means no signature.",
    )
    include_profile_picture = serializers.BooleanField(
        help_text="Whether to show your Gravatar profile picture next to the signature.",
    )


class _SingletonSchema(PostHogAutoSchema):
    """Prevents drf-spectacular from wrapping the ``list`` response in an array.

    Each user has one signature per project, not a collection of them.
    """

    def _is_list_view(self, serializer: object = None) -> bool:
        return False


class AgentSignatureViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    schema = _SingletonSchema()
    scope_object = "ticket"
    pagination_class = None
    serializer_class = AgentSignatureSerializer

    def _user(self) -> User:
        return cast(User, self.request.user)

    @extend_schema(
        responses=AgentSignatureSerializer,
        description="Your own email signature for support replies in this project.",
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        signature = AgentSignature.objects.filter(team_id=self.team_id, user=self._user()).first()
        data = (
            {"text": signature.text, "include_profile_picture": signature.include_profile_picture}
            if signature
            else {"text": "", "include_profile_picture": True}
        )
        return Response(AgentSignatureSerializer(data).data)

    @validated_request(
        request_serializer=AgentSignatureSerializer,
        responses={200: AgentSignatureSerializer},
        description="Save your own email signature for support replies in this project.",
    )
    def create(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        signature, _ = AgentSignature.objects.update_or_create(
            team_id=self.team_id,
            user=self._user(),
            defaults={
                "text": request.validated_data["text"],
                "include_profile_picture": request.validated_data["include_profile_picture"],
            },
        )
        return Response(
            AgentSignatureSerializer(
                {"text": signature.text, "include_profile_picture": signature.include_profile_picture}
            ).data
        )
