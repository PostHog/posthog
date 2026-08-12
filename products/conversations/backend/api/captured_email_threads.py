from uuid import UUID

from django.db.models import Prefetch

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.models.user import User

from products.conversations.backend.models import (
    EmailThread,
    EmailThreadMessage,
    EmailThreadMessageDirection,
    EmailThreadParticipant,
    EmailThreadParticipantKind,
)


class CapturedEmailAddressSerializer(serializers.Serializer):
    name = serializers.CharField(allow_blank=True, help_text="Name from the email header.")
    email = serializers.EmailField(help_text="Email address from the email header.")


class CapturedEmailParticipantSerializer(serializers.Serializer):
    email = serializers.EmailField(help_text="Normalized participant email address.")
    display_name = serializers.CharField(allow_blank=True, help_text="Participant name from the email header.")
    participant_kind = serializers.ChoiceField(
        choices=EmailThreadParticipantKind.choices,
        help_text="Whether the participant belongs to the PostHog organization.",
    )


class CapturedEmailThreadSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Captured email thread ID.")
    subject = serializers.CharField(allow_blank=True, help_text="Email thread subject.")
    preview = serializers.CharField(allow_blank=True, help_text="Preview of the latest captured message.")
    first_message_at = serializers.DateTimeField(allow_null=True, help_text="Source timestamp of the first message.")
    last_message_at = serializers.DateTimeField(allow_null=True, help_text="Source timestamp of the latest message.")
    message_count = serializers.IntegerField(min_value=0, help_text="Number of captured messages in the thread.")
    participants = CapturedEmailParticipantSerializer(many=True, help_text="People included in the email thread.")


class CapturedEmailMessageSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Captured message ID.")
    sent_at = serializers.DateTimeField(help_text="Timestamp from the source email.")
    sender = CapturedEmailAddressSerializer(help_text="Sender from the email From header.")
    to_recipients = CapturedEmailAddressSerializer(many=True, help_text="Recipients from the email To header.")
    cc_recipients = CapturedEmailAddressSerializer(many=True, help_text="Recipients from the email Cc header.")
    sender_authenticated = serializers.BooleanField(
        help_text="Whether Mailgun authentication verified the sender domain.",
    )
    direction = serializers.ChoiceField(
        choices=EmailThreadMessageDirection.choices,
        help_text="Whether PostHog received or sent the message.",
    )
    content = serializers.CharField(allow_blank=True, help_text="Plain-text email content.")


class CapturedEmailThreadDetailSerializer(CapturedEmailThreadSummarySerializer):
    messages = CapturedEmailMessageSerializer(many=True, help_text="Messages ordered by their source timestamp.")


class CapturedEmailThreadListQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        default=50,
        min_value=1,
        max_value=100,
        required=False,
        help_text="Maximum number of threads to return.",
    )
    offset = serializers.IntegerField(
        default=0,
        min_value=0,
        required=False,
        help_text="Number of threads to skip.",
    )


class CapturedEmailThreadListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField(min_value=0, help_text="Total number of accessible captured email threads.")
    results = CapturedEmailThreadSummarySerializer(many=True, help_text="Captured email threads for this user.")


class CapturedEmailThreadErrorSerializer(serializers.Serializer):
    error = serializers.CharField(help_text="Reason the request failed.")


def _request_user_and_team_id(request: Request) -> tuple[User, int] | Response:
    user = request.user
    if not isinstance(user, User) or user.current_team_id is None:
        return Response({"error": "No current team selected"}, status=400)
    return user, user.current_team_id


def _participant_to_dict(participant: EmailThreadParticipant) -> dict[str, object]:
    return {
        "email": participant.email,
        "display_name": participant.display_name,
        "participant_kind": participant.kind,
    }


def _thread_to_dict(thread: EmailThread) -> dict[str, object]:
    return {
        "id": thread.id,
        "subject": thread.subject,
        "preview": thread.preview,
        "first_message_at": thread.first_message_at,
        "last_message_at": thread.last_message_at,
        "message_count": thread.message_count,
        "participants": [_participant_to_dict(participant) for participant in thread.participants.all()],
    }


def _message_to_dict(message: EmailThreadMessage) -> dict[str, object]:
    return {
        "id": message.id,
        "sent_at": message.sent_at,
        "sender": {"name": message.sender_name, "email": message.sender_email},
        "to_recipients": message.to_recipients,
        "cc_recipients": message.cc_recipients,
        "sender_authenticated": message.sender_authenticated,
        "direction": message.direction,
        "content": message.comment.content,
    }


class CapturedEmailThreadListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[CapturedEmailThreadListQuerySerializer],
        responses={
            200: CapturedEmailThreadListResponseSerializer,
            400: OpenApiResponse(response=CapturedEmailThreadErrorSerializer),
        },
    )
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        request_context = _request_user_and_team_id(request)
        if isinstance(request_context, Response):
            return request_context
        user, team_id = request_context

        query_serializer = CapturedEmailThreadListQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        limit: int = query_serializer.validated_data["limit"]
        offset: int = query_serializer.validated_data["offset"]

        threads = (
            EmailThread.objects.for_team(team_id)
            .filter(access_grants__team_id=team_id, access_grants__user_id=user.id)
            .prefetch_related(Prefetch("participants", queryset=EmailThreadParticipant.objects.for_team(team_id)))
            .order_by("-last_message_at", "-id")
        )
        count = threads.count()
        results = [_thread_to_dict(thread) for thread in threads[offset : offset + limit]]
        return Response({"count": count, "results": results})


class CapturedEmailThreadDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: CapturedEmailThreadDetailSerializer,
            400: OpenApiResponse(response=CapturedEmailThreadErrorSerializer),
            404: OpenApiResponse(response=CapturedEmailThreadErrorSerializer),
        },
    )
    def get(self, request: Request, thread_id: UUID, *args: object, **kwargs: object) -> Response:
        request_context = _request_user_and_team_id(request)
        if isinstance(request_context, Response):
            return request_context
        user, team_id = request_context

        thread = (
            EmailThread.objects.for_team(team_id)
            .filter(id=thread_id, access_grants__team_id=team_id, access_grants__user_id=user.id)
            .prefetch_related(Prefetch("participants", queryset=EmailThreadParticipant.objects.for_team(team_id)))
            .first()
        )
        if thread is None:
            return Response({"error": "Captured email thread not found"}, status=404)

        messages = (
            EmailThreadMessage.objects.for_team(team_id)
            .filter(thread=thread)
            .select_related("comment")
            .order_by("sent_at", "id")
        )
        response_data = _thread_to_dict(thread)
        response_data["messages"] = [_message_to_dict(message) for message in messages]
        return Response(response_data)
