from datetime import datetime, UTC
from typing import cast

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from loginas.utils import is_impersonated_session
from rest_framework import request, serializers, status, viewsets, filters
from rest_framework.decorators import action
from rest_framework.request import Request
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
from posthog.models.chat import ChatConversation, ChatMessage
from posthog.models.person.person import Person
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.utils_cors import cors_response


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

    class Meta:
        model = ChatConversation
        fields = [
            "id",
            "title",
            "person",
            "created_at",
            "updated_at",
            "source_url",
            "unread_count",
            "messages",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ChatConversationViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "chat_conversation"
    queryset = ChatConversation.objects.all()
    serializer_class = ChatConversationSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["title", "person__properties"]

    def get_queryset(self):
        queryset = super().get_queryset().filter(team_id=self.team_id)
        return queryset.order_by("-updated_at")

    def perform_create(self, serializer):
        person_id = serializer.validated_data.pop("person", None)
        if not person_id:
            raise serializers.ValidationError("Person ID is required")

        try:
            person = Person.objects.get(id=person_id, team_id=self.team_id)
        except Person.DoesNotExist:
            raise serializers.ValidationError("Person not found")

        serializer.save(
            person=person,
            team_id=self.team_id,
        )

        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=cast(User, self.request.user),
            was_impersonated=is_impersonated_session(self.request),
            item_id=serializer.instance.id,
            scope="ChatConversation",
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
                scope="ChatConversation",
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
            scope="ChatConversation",
            activity="deleted",
            detail=Detail(name=instance.title or f"Chat {instance.id}"),
        )

        return super().destroy(request, *args, **kwargs)

    @action(methods=["GET"], url_path="activity", detail=False)
    def all_activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_activity(scope="ChatConversation", team_id=self.team_id, limit=limit, page=page)
        return activity_page_response(activity_page, limit, page, request)

    @action(methods=["GET"], detail=True)
    def activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        item_id = kwargs["pk"]

        if not ChatConversation.objects.filter(id=item_id, team_id=self.team_id).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)

        activity_page = load_activity(
            scope="ChatConversation",
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

    def get_queryset(self):
        queryset = super().get_queryset()
        conversation_id = self.request.query_params.get("conversation_id", None)

        if conversation_id:
            queryset = queryset.filter(conversation_id=conversation_id)

        return queryset.order_by("created_at")

    def perform_create(self, serializer):
        conversation_id = self.kwargs.get("conversation_pk")
        conversation = ChatConversation.objects.get(id=conversation_id, team_id=self.team_id)

        # Update conversation's updated_at timestamp
        conversation.updated_at = datetime.now(UTC)
        conversation.save(update_fields=["updated_at"])

        serializer.save(conversation=conversation)


@csrf_exempt
def public_chat_endpoint(request: Request):
    """
    This endpoint is intended to be called from the client-side widget.
    It handles creating/updating conversations and messages from external users.
    """
    token = get_token(None, request)
    if request.method == "OPTIONS":
        return cors_response(request, HttpResponse(""))

    if not token:
        return cors_response(
            request,
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
            request,
            generate_exception_response(
                "chat",
                "Project API key invalid. You can find your project API key in your PostHog project settings.",
                type="authentication_error",
                code="invalid_api_key",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
        )

    if request.method == "POST":
        try:
            data = request.json()
            action = data.get("action")

            if action == "create_conversation":
                distinct_id = data.get("distinct_id")

                if not distinct_id:
                    return cors_response(
                        request,
                        JsonResponse(
                            {"status": "error", "message": "Missing distinct_id"}, status=status.HTTP_400_BAD_REQUEST
                        ),
                    )

                # Find or create person for this distinct_id
                try:
                    from posthog.models.person.util import get_or_create_person_from_distinct_id

                    person = get_or_create_person_from_distinct_id(team_id=team.id, distinct_id=distinct_id)
                except Exception as e:
                    return cors_response(
                        request,
                        JsonResponse(
                            {"status": "error", "message": f"Error finding person: {str(e)}"},
                            status=status.HTTP_400_BAD_REQUEST,
                        ),
                    )

                initial_message = data.get("message")
                title = data.get("title")
                source_url = data.get("source_url")

                # Create conversation
                conversation = ChatConversation.objects.create(
                    team=team,
                    person=person,
                    title=title,
                    source_url=source_url,
                )

                # Add initial message if provided
                if initial_message:
                    ChatMessage.objects.create(
                        conversation=conversation,
                        content=initial_message,
                    )

                return cors_response(
                    request, JsonResponse({"status": "success", "conversation_id": str(conversation.id)})
                )

            elif action == "send_message":
                conversation_id = data.get("conversation_id")
                message = data.get("message")

                if not conversation_id or not message:
                    return cors_response(
                        request,
                        JsonResponse(
                            {"status": "error", "message": "Missing conversation_id or message"},
                            status=status.HTTP_400_BAD_REQUEST,
                        ),
                    )

                try:
                    conversation = ChatConversation.objects.get(id=conversation_id, team=team)
                except ChatConversation.DoesNotExist:
                    return cors_response(
                        request,
                        JsonResponse(
                            {"status": "error", "message": "Conversation not found"}, status=status.HTTP_404_NOT_FOUND
                        ),
                    )

                # Reset unread count when user sends a message
                conversation.unread_count = 0
                conversation.save(update_fields=["unread_count", "updated_at"])

                # Create message
                chat_message = ChatMessage.objects.create(
                    conversation=conversation,
                    content=message,
                )

                return cors_response(
                    request,
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

                if not conversation_id:
                    return cors_response(
                        request,
                        JsonResponse(
                            {"status": "error", "message": "Missing conversation_id"},
                            status=status.HTTP_400_BAD_REQUEST,
                        ),
                    )

                try:
                    conversation = ChatConversation.objects.get(id=conversation_id, team=team)
                except ChatConversation.DoesNotExist:
                    return cors_response(
                        request,
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
                        }
                    )

                # Mark all unread messages as read when user gets messages
                ChatMessage.objects.filter(conversation=conversation, read=False).update(read=True)

                # Reset unread count when user gets messages
                conversation.unread_count = 0
                conversation.save(update_fields=["unread_count"])

                return cors_response(
                    request,
                    JsonResponse(
                        {
                            "status": "success",
                            "messages": messages_data,
                            "conversation": {
                                "id": str(conversation.id),
                                "created_at": conversation.created_at.isoformat(),
                                "updated_at": conversation.updated_at.isoformat(),
                            },
                        }
                    ),
                )

            else:
                return cors_response(
                    request,
                    JsonResponse(
                        {"status": "error", "message": f"Invalid action: {action}"}, status=status.HTTP_400_BAD_REQUEST
                    ),
                )

        except Exception as e:
            return cors_response(
                request,
                JsonResponse({"status": "error", "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR),
            )

    return cors_response(
        request,
        JsonResponse({"status": "error", "message": "Method not allowed"}, status=status.HTTP_405_METHOD_NOT_ALLOWED),
    )
