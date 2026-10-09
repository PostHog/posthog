import re
import json
import hashlib
from typing import TYPE_CHECKING, cast

from django.http import HttpResponse

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied, Throttled, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.auth import SessionAuthentication
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false
from posthog.redis import get_client
from posthog.token_bucket import BucketUnavailable, Budget, consume

if TYPE_CHECKING:
    from redis.client import Pipeline

# Browser terminals exchange WebRTC session descriptions through short-lived mailboxes.
# Game traffic flows directly between browsers, so this only carries a few messages per player.
HOST = "host"
ROOM_TTL_SECONDS = 30
MAILBOX_TTL_SECONDS = 60
MAILBOX_LIMIT = 16
OFFER_BUDGET = Budget(burst=4, per_hour=120)
ROOM_SIGNAL_BUDGET = Budget(burst=16, per_hour=3600)
PEER_PATTERN = r"^[a-z0-9]{1,32}$"
ROOM_PATTERN = r"^[A-Z0-9]{4,12}$"
TOKEN_HEADER = "X-Terminal-Netplay-Token"
TOKEN_PARAMETER = OpenApiParameter(
    TOKEN_HEADER,
    str,
    OpenApiParameter.HEADER,
    required=True,
    pattern=r"^[a-f0-9]{64}$",
    description="Random token unique to this terminal's game. Keep it private and reuse it for all signaling requests.",
)


class TerminalNetplayRoom:
    def __init__(self, team_id: int, room: str, owner: str, user_id: int) -> None:
        self.key = f"terminal_netplay:{team_id}:{room}"
        self.owner = owner.encode()
        self.user_id = user_id
        self.client = get_client()

    def _host(self, pipeline: Pipeline) -> bytes:
        host = cast(bytes | None, pipeline.get(self.key))
        if host is None:
            raise NotFound("No deathmatch room has this code. Check the code and try again.")
        return host

    def _check_owner(self, owner: bytes | None) -> None:
        if owner != self.owner:
            raise PermissionDenied("This terminal does not own that player. Start a new game and try again.")

    def _mailbox_key(self, host: bytes, peer: str) -> str:
        # A new host token isolates mailboxes left behind by an expired room with the same code.
        return f"{self.key}:{host.decode()}:{peer}"

    def _peer_owner(self, pipeline: Pipeline, host: bytes, peer: str) -> bytes | None:
        if peer == HOST:
            return host
        key = f"{self._mailbox_key(host, peer)}:owner"
        pipeline.watch(key)
        return cast(bytes | None, pipeline.get(key))

    def _consume_budget(self, key: str, budget: Budget) -> None:
        decision = consume(key, budget, client=self.client)
        if isinstance(decision, BucketUnavailable):
            raise Throttled(wait=1, detail="Signaling is temporarily unavailable. Try again.")
        if not decision.allowed:
            raise Throttled(wait=decision.retry_after, detail="Too many connection attempts. Wait and try again.")

    def send(self, sender: str, recipient: str, description: dict[str, str]) -> None:
        is_offer = sender != HOST and recipient == HOST and description["type"] == "offer"
        is_answer = sender == HOST and recipient != HOST and description["type"] == "answer"
        if not (is_offer or is_answer):
            raise ValidationError("Send offers to the host and answers to the joining player.")
        direction = description["type"]
        self._consume_budget(
            f"{self.key}:rate:{direction}:user:{self.user_id}", OFFER_BUDGET if is_offer else ROOM_SIGNAL_BUDGET
        )
        room_charged = False

        def deliver(pipeline: Pipeline) -> None:
            nonlocal room_charged
            host = self._host(pipeline)
            registered_owner = self._peer_owner(pipeline, host, sender)
            if is_answer or registered_owner is not None:
                self._check_owner(registered_owner)
            recipient_owner = self._peer_owner(pipeline, host, recipient) if is_answer else None
            if is_answer and recipient_owner is None:
                raise NotFound("This player is no longer in the room. Ask them to join again.")
            key = self._mailbox_key(host, recipient)
            pipeline.watch(key)
            if cast(int, pipeline.llen(key)) >= MAILBOX_LIMIT:
                raise Throttled(wait=1, detail="This player's connection mailbox is full. Try again shortly.")
            if not room_charged:
                self._consume_budget(f"{self.key}:rate:{direction}", ROOM_SIGNAL_BUDGET)
                room_charged = True
            message = json.dumps({"sender": sender, "description": description})
            pipeline.multi()
            if is_offer:
                pipeline.set(f"{self._mailbox_key(host, sender)}:owner", self.owner, ex=MAILBOX_TTL_SECONDS)
            elif recipient_owner is not None:
                pipeline.set(f"{key}:owner", recipient_owner, ex=MAILBOX_TTL_SECONDS)
            pipeline.rpush(key, message)
            pipeline.expire(key, MAILBOX_TTL_SECONDS)

        self.client.transaction(deliver, self.key)

    def read(self, peer: str) -> list[bytes]:
        def consume(pipeline: Pipeline) -> None:
            host = cast(bytes | None, pipeline.get(self.key))
            if peer == HOST:
                if host is not None:
                    self._check_owner(host)
                host = self.owner
            else:
                host = self._host(pipeline)
                self._check_owner(self._peer_owner(pipeline, host, peer))
            key = self._mailbox_key(host, peer)
            pipeline.multi()
            if peer == HOST:
                pipeline.set(self.key, self.owner, ex=ROOM_TTL_SECONDS)
            pipeline.lrange(key, 0, -1)
            pipeline.delete(key)

        return cast(list[bytes], self.client.transaction(consume, self.key)[-2])


class TerminalNetplayDescriptionSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["offer", "answer"], help_text="WebRTC session description type.")
    # Chrome requires the final SDP line ending when applying a remote description.
    sdp = serializers.CharField(
        max_length=16384, trim_whitespace=False, help_text="WebRTC session description with ICE candidates."
    )


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
        if not isinstance(request.successful_authenticator, SessionAuthentication):
            raise PermissionDenied("Sign in to use the terminal.")
        user = cast(User, request.user)
        if not feature_enabled_or_false(
            "posthog-terminal",
            str(user.distinct_id),
            groups={"organization": str(self.team.organization_id)},
        ):
            raise PermissionDenied("The terminal is not enabled for this account.")

    def _room(self, request: Request, room: str) -> TerminalNetplayRoom:
        token = request.headers.get(TOKEN_HEADER, "")
        if re.fullmatch(r"[a-f0-9]{64}", token) is None:
            raise PermissionDenied("The game token is missing or invalid. Start a new game and try again.")
        user = cast(User, request.user)
        owner = hashlib.sha256(f"{user.pk}:{token}".encode()).hexdigest()
        return TerminalNetplayRoom(self.team_id, room, owner, user.pk)

    @extend_schema(
        tags=["core"],
        request=TerminalNetplaySignalSerializer,
        parameters=[TOKEN_PARAMETER],
        responses={204: OpenApiResponse(description="Delivered."), 404: OpenApiResponse(description="No such room.")},
        description="Send a WebRTC session description to another terminal in a Doom room.",
    )
    @action(methods=["POST"], detail=False)
    def signal(self, request: Request, **kwargs: object) -> HttpResponse:
        self._check_enabled(request)
        serializer = TerminalNetplaySignalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        self._room(request, data["room"]).send(data["sender"], data["recipient"], data["description"])
        return HttpResponse(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        tags=["core"],
        parameters=[TerminalNetplayMailboxQuerySerializer, TOKEN_PARAMETER],
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
        messages = self._room(request, room).read(peer)
        return Response({"signals": [json.loads(message) for message in messages]})
