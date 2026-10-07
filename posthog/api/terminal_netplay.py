import json
from typing import cast

from django.http import HttpResponse

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.auth import SessionAuthentication
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false
from posthog.redis import get_client

# Browser terminals exchange WebRTC session descriptions through short-lived mailboxes.
# Game traffic flows directly between browsers, so this only carries a few messages per player.
HOST = "host"
ROOM_TTL_SECONDS = 30
MAILBOX_TTL_SECONDS = 60
MAILBOX_LIMIT = 16
PEER_PATTERN = r"^[a-z0-9]{1,32}$"
ROOM_PATTERN = r"^[A-Z0-9]{4,12}$"


class TerminalNetplayDescriptionSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["offer", "answer"], help_text="WebRTC session description type.")
    sdp = serializers.CharField(max_length=16384, help_text="WebRTC session description with ICE candidates.")


class TerminalNetplaySignalSerializer(serializers.Serializer):
    room = serializers.RegexField(ROOM_PATTERN, help_text="Room code shown by the game host.")
    sender = serializers.RegexField(PEER_PATTERN, help_text="Peer that sent the description.")
    recipient = serializers.RegexField(PEER_PATTERN, help_text="Peer that receives the description.")
    description = TerminalNetplayDescriptionSerializer()


class TerminalNetplayMailboxQuerySerializer(serializers.Serializer):
    room = serializers.RegexField(ROOM_PATTERN, help_text="Room code shown by the game host.")
    peer = serializers.RegexField(PEER_PATTERN, help_text="Peer whose mailbox to read. The host reads 'host'.")


class TerminalNetplayReceivedSignalSerializer(serializers.Serializer):
    sender = serializers.CharField(help_text="Peer that sent the description.")
    description = TerminalNetplayDescriptionSerializer()


class TerminalNetplayMailboxSerializer(serializers.Serializer):
    signals = TerminalNetplayReceivedSignalSerializer(many=True, help_text="Descriptions received since the last read.")


class TerminalNetplayViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    authentication_classes = [SessionAuthentication]

    def _check_enabled(self, request: Request) -> None:
        user = cast(User, request.user)
        if not feature_enabled_or_false(
            "posthog-terminal",
            str(user.distinct_id),
            groups={"organization": str(self.team.organization_id)},
        ):
            raise PermissionDenied("The terminal is not enabled for this account.")

    def _room_key(self, room: str) -> str:
        return f"terminal_netplay:{self.team.id}:{room}"

    def _mailbox_key(self, room: str, peer: str) -> str:
        return f"{self._room_key(room)}:{peer}"

    @extend_schema(
        tags=["core"],
        request=TerminalNetplaySignalSerializer,
        responses={204: OpenApiResponse(description="Delivered."), 404: OpenApiResponse(description="No such room.")},
        description="Send a WebRTC session description to another terminal in a Doom room.",
    )
    @action(methods=["POST"], detail=False)
    def signal(self, request: Request, **kwargs: object) -> HttpResponse:
        self._check_enabled(request)
        serializer = TerminalNetplaySignalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        client = get_client()
        if data["recipient"] == HOST and not client.exists(self._room_key(data["room"])):
            raise NotFound("No deathmatch room has this code. Check the code and try again.")
        key = self._mailbox_key(data["room"], data["recipient"])
        message = json.dumps({"sender": data["sender"], "description": data["description"]})
        pipeline = client.pipeline()
        pipeline.rpush(key, message)
        pipeline.ltrim(key, -MAILBOX_LIMIT, -1)
        pipeline.expire(key, MAILBOX_TTL_SECONDS)
        pipeline.execute()
        return HttpResponse(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        tags=["core"],
        parameters=[TerminalNetplayMailboxQuerySerializer],
        responses={200: TerminalNetplayMailboxSerializer},
        description="Read and clear a terminal's WebRTC mailbox. Reading the host mailbox keeps the room open.",
    )
    @action(methods=["GET"], detail=False)
    def mailbox(self, request: Request, **kwargs: object) -> Response:
        self._check_enabled(request)
        serializer = TerminalNetplayMailboxQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        room = serializer.validated_data["room"]
        peer = serializer.validated_data["peer"]
        key = self._mailbox_key(room, peer)
        pipeline = get_client().pipeline()
        if peer == HOST:
            pipeline.set(self._room_key(room), 1, ex=ROOM_TTL_SECONDS)
        pipeline.lrange(key, 0, -1)
        pipeline.delete(key)
        messages = pipeline.execute()[-2]
        return Response({"signals": [json.loads(message) for message in messages]})
