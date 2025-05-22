from datetime import datetime, UTC
from typing import cast

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from loginas.utils import is_impersonated_session
from posthog.api.person import PersonSerializer
from rest_framework import request, serializers, status, viewsets, filters
from rest_framework.decorators import action
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import get_token
from posthog.exceptions import generate_exception_response
from posthog.models.activity_logging.activity_log import (
    Detail,
    changes_between,
    load_activity,
    log_activity,
)
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.person.util import get_persons_by_distinct_ids
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.utils_cors import cors_response

from .models import ChatConversation, ChatMessage


class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = [
            "id",
            "content",
            "created_at",
            "read",
            "is_assistant",
        ]
        read_only_fields = ["id", "created_at"]


class ChatConversationSerializer(serializers.ModelSerializer):
    messages = ChatMessageSerializer(many=True, read_only=True)
    distinct_id = serializers.CharField()
    person = PersonSerializer(read_only=True)

    class Meta:
        model = ChatConversation
        fields = [
            "id",
            "title",
            "person",
            "person_uuid",
            "distinct_id",
            "created_at",
            "updated_at",
            "source_url",
            "unread_count",
            "messages",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        request = self.context.get("request")
        if request and request.method == "POST":
            self.fields["person_uuid"].required = False


class ChatConversationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "chat_conversation"
    queryset = ChatConversation.objects.all()
    serializer_class = ChatConversationSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["title"]

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team_id).order_by("-updated_at")

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        is_assistant = request.query_params.get("is_assistant", None)

        # Mark messages from the opposite side as read
        if is_assistant is not None:
            is_assistant_bool = is_assistant.lower() == "true"
            # Update messages from the opposite side
            instance.messages.filter(is_assistant=not is_assistant_bool, read=False).update(read=True)

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def perform_create(self, serializer):
        distinct_id = self.request.data["distinct_id"]
        if not distinct_id:
            raise serializers.ValidationError("Distinct id UUID is required")

        persons = get_persons_by_distinct_ids(team_id=self.team.id, distinct_ids=[distinct_id])
        if persons.exists():
            person = persons.first()
            person_uuid = person.uuid
        else:
            person_uuid = None

        serializer.save(
            team_id=self.team_id,
            person_uuid=person_uuid,
        )

        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=cast(User, self.request.user),
            was_impersonated=is_impersonated_session(self.request),
            item_id=serializer.instance.id,
            scope="chat_conversation",
            activity="created",
            detail=Detail(name=serializer.instance.title or f"Chat {serializer.instance.id}"),
        )

    def perform_update(self, serializer):
        before_update = ChatConversation.objects.get(pk=serializer.instance.pk)
        serializer.save()

        changes = changes_between(
            "ChatConversation",
            previous=before_update,
            current=serializer.instance,
        )

        if changes:
            log_activity(
                organization_id=self.organization.id,
                team_id=self.team_id,
                user=cast(User, self.request.user),
                was_impersonated=is_impersonated_session(self.request),
                item_id=serializer.instance.id,
                scope="chat_conversation",
                activity="updated",
                detail=Detail(changes=changes, name=serializer.instance.title or f"Chat {serializer.instance.id}"),
            )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()

        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=cast(User, self.request.user),
            was_impersonated=is_impersonated_session(request),
            item_id=instance.id,
            scope="chat_conversation",
            activity="deleted",
            detail=Detail(name=instance.title or f"Chat {instance.id}"),
        )

        return super().destroy(request, *args, **kwargs)

    @action(methods=["GET"], url_path="activity", detail=False)
    def all_activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_activity(scope="chat_conversation", team_id=self.team_id, limit=limit, page=page)
        return activity_page_response(activity_page, limit, page, request)

    @action(methods=["GET"], detail=True)
    def activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        item_id = kwargs["pk"]

        if not ChatConversation.objects.filter(id=item_id, team_id=self.team_id).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)

        activity_page = load_activity(
            scope="chat_conversation",
            team_id=self.team_id,
            item_ids=[item_id],
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)


class ChatMessageViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "chat_message"
    queryset = ChatMessage.objects.all()
    serializer_class = ChatMessageSerializer

    def safely_get_queryset(self, queryset):
        # The parent conversation ID should be accessed via the parents_query_dict
        conversation_id = (
            self.parents_query_dict.get("conversation_id") if hasattr(self, "parents_query_dict") else None
        )

        if not conversation_id:
            conversation_id = self.request.query_params.get("conversation_id")

        if conversation_id:
            queryset = queryset.filter(conversation_id=conversation_id)

        return queryset.order_by("created_at")

    def perform_create(self, serializer):
        # The parent conversation ID should be accessed via the parents_query_dict
        conversation_id = (
            self.parents_query_dict.get("conversation_id") if hasattr(self, "parents_query_dict") else None
        )

        if not conversation_id:
            raise serializers.ValidationError("Conversation ID is required")

        try:
            conversation = ChatConversation.objects.get(id=conversation_id, team_id=self.team_id)
        except ChatConversation.DoesNotExist:
            raise serializers.ValidationError(f"Conversation with ID {conversation_id} not found")

        conversation.updated_at = datetime.now(UTC)
        conversation.save(update_fields=["updated_at"])

        serializer.save(conversation=conversation)


@csrf_exempt
def chat_endpoints(http_request: HttpResponse):
    """
    This endpoint is the unified entry point for chat functionality, handling both
    internal authenticated requests and external client-side widget requests.
    """
    token = get_token(None, http_request)

    if not token and http_request.method == "POST":
        try:
            if http_request.content_type == "application/json":
                import json

                body_data = json.loads(http_request.body)
                token = body_data.get("token") or body_data.get("api_key")
        except Exception:
            pass

    if http_request.method == "OPTIONS":
        return cors_response(http_request, HttpResponse(""))

    if not token:
        return cors_response(
            http_request,
            generate_exception_response(
                "chat",
                "API key not provided. You can find your project API key in your PostHog project settings.",
                type="authentication_error",
                code="missing_api_key",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
        )

    team = Team.objects.get_team_from_cache_or_token(token)
    if team is None:
        return cors_response(
            http_request,
            generate_exception_response(
                "chat",
                "Project API key invalid. You can find your project API key in your PostHog project settings.",
                type="authentication_error",
                code="invalid_api_key",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
        )

    if http_request.method == "POST":
        try:
            import json

            data = json.loads(http_request.body) if http_request.content_type == "application/json" else {}
            action = data.get("action")

            if action == "create_conversation":
                distinct_id = data.get("distinct_id")

                if not distinct_id:
                    return cors_response(
                        http_request,
                        JsonResponse(
                            {"status": "error", "message": "Missing distinct_id"}, status=status.HTTP_400_BAD_REQUEST
                        ),
                    )

                try:
                    persons = get_persons_by_distinct_ids(team_id=team.id, distinct_ids=[distinct_id])
                    if persons.exists():
                        person = persons.first()
                        person_uuid = person.uuid
                    else:
                        person_uuid = None
                except Exception as e:
                    return cors_response(
                        http_request,
                        JsonResponse(
                            {"status": "error", "message": f"Error finding person: {str(e)}"},
                            status=status.HTTP_400_BAD_REQUEST,
                        ),
                    )

                initial_message = data.get("message")
                title = data.get("title")
                source_url = data.get("source_url")

                conversation = ChatConversation.objects.create(
                    team=team,
                    distinct_id=distinct_id,
                    person_uuid=person_uuid,
                    title=title,
                    source_url=source_url,
                )

                if initial_message:
                    ChatMessage.objects.create(
                        conversation=conversation,
                        content=initial_message,
                    )

                return cors_response(
                    http_request, JsonResponse({"status": "success", "conversation_id": str(conversation.id)})
                )

            elif action == "send_message":
                conversation_id = data.get("conversation_id")
                message = data.get("message")
                distinct_id = data.get("distinct_id")

                if not conversation_id or not message:
                    return cors_response(
                        http_request,
                        JsonResponse(
                            {"status": "error", "message": "Missing conversation_id or message"},
                            status=status.HTTP_400_BAD_REQUEST,
                        ),
                    )

                if not distinct_id:
                    return cors_response(
                        http_request,
                        JsonResponse(
                            {"status": "error", "message": "Missing distinct_id"}, status=status.HTTP_400_BAD_REQUEST
                        ),
                    )

                try:
                    conversation = ChatConversation.objects.get(id=conversation_id, team=team, distinct_id=distinct_id)
                except ChatConversation.DoesNotExist:
                    return cors_response(
                        http_request,
                        JsonResponse(
                            {"status": "error", "message": "Conversation not found"}, status=status.HTTP_404_NOT_FOUND
                        ),
                    )

                conversation.unread_count = 0
                conversation.save(update_fields=["unread_count", "updated_at"])

                chat_message = ChatMessage.objects.create(
                    conversation=conversation,
                    content=message,
                )

                return cors_response(
                    http_request,
                    JsonResponse(
                        {
                            "status": "success",
                            "message_id": str(chat_message.id),
                            "conversation_id": str(conversation.id),
                        }
                    ),
                )

            elif action == "get_messages":
                conversation_id = data.get("conversation_id")
                is_assistant = data.get("is_assistant")
                distinct_id = data.get("distinct_id")

                if not conversation_id:
                    return cors_response(
                        http_request,
                        JsonResponse(
                            {"status": "error", "message": "Missing conversation_id"},
                            status=status.HTTP_400_BAD_REQUEST,
                        ),
                    )

                try:
                    conversation = ChatConversation.objects.get(id=conversation_id, team=team, distinct_id=distinct_id)
                except ChatConversation.DoesNotExist:
                    return cors_response(
                        http_request,
                        JsonResponse(
                            {"status": "error", "message": "Conversation not found"}, status=status.HTTP_404_NOT_FOUND
                        ),
                    )

                messages = ChatMessage.objects.filter(conversation=conversation).order_by("created_at")

                messages_data = []
                for message in messages:
                    messages_data.append(
                        {
                            "id": str(message.id),
                            "content": message.content,
                            "created_at": message.created_at.isoformat(),
                            "read": message.read,
                            "is_assistant": message.is_assistant,
                        }
                    )

                # Mark messages as read based on is_assistant flag
                if is_assistant is not None:
                    is_assistant_bool = is_assistant is True or (
                        isinstance(is_assistant, str) and is_assistant.lower() == "true"
                    )
                    # Update messages from the opposite side
                    ChatMessage.objects.filter(
                        conversation=conversation, is_assistant=not is_assistant_bool, read=False
                    ).update(read=True)

                # Reset unread count
                conversation.unread_count = 0
                conversation.save(update_fields=["unread_count"])

                return cors_response(
                    http_request,
                    JsonResponse(
                        {
                            "status": "success",
                            "messages": messages_data,
                            "conversation": {
                                "id": str(conversation.id),
                                "created_at": conversation.created_at.isoformat(),
                                "updated_at": conversation.updated_at.isoformat(),
                                "distinct_id": conversation.distinct_id,
                            },
                        }
                    ),
                )

            else:
                return cors_response(
                    http_request,
                    JsonResponse(
                        {"status": "error", "message": f"Invalid action: {action}"}, status=status.HTTP_400_BAD_REQUEST
                    ),
                )

        except Exception as e:
            return cors_response(
                http_request,
                JsonResponse({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR),
            )
    elif http_request.method == "GET":
        distinct_id = http_request.GET.get("distinct_id")
        if not distinct_id:
            raise serializers.ValidationError("Distinct id UUID is required")

        conversations = ChatConversation.objects.filter(team=team, distinct_id=distinct_id).order_by("-updated_at")
        conversations_data = []

        for conversation in conversations[:20]:
            # Fetch messages for the current conversation
            messages_qs = ChatMessage.objects.filter(conversation=conversation).order_by("created_at")
            current_conv_messages_data = []
            for message_obj in messages_qs:
                current_conv_messages_data.append(
                    {
                        "id": str(message_obj.id),
                        "content": message_obj.content,
                        "created_at": message_obj.created_at.isoformat(),
                        "read": message_obj.read,
                        "is_assistant": message_obj.is_assistant,
                    }
                )

            conversations_data.append(
                {
                    "id": str(conversation.id),
                    "title": conversation.title,
                    "created_at": conversation.created_at.isoformat(),
                    "updated_at": conversation.updated_at.isoformat(),
                    "unread_count": conversation.unread_count,
                    "distinct_id": conversation.distinct_id,
                    "messages": current_conv_messages_data,
                }
            )

        return cors_response(http_request, JsonResponse({"status": "success", "conversations": conversations_data}))

    return cors_response(
        http_request,
        JsonResponse({"status": "error", "message": "Method not allowed"}, status=status.HTTP_405_METHOD_NOT_ALLOWED),
    )
