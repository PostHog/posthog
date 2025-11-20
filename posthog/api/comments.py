from typing import Any, cast

from django.db import transaction
from django.db.models import Q, QuerySet

from rest_framework import exceptions, pagination, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import ClassicBehaviorBooleanFieldSerializer, action
from posthog.models.comment import Comment
from posthog.tasks.email import send_discussions_mentioned


class CommentSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    deleted = ClassicBehaviorBooleanFieldSerializer()
    mentions = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)
    slug = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = Comment
        exclude = ["team"]
        read_only_fields = ["id", "created_by", "version"]

    def has_empty_paragraph(self, doc):
        for node in doc.get("content", []):
            if node.get("type") == "paragraph":
                content = node.get("content", [])
                if len(content) == 1 and content[0].get("type") == "text" and content[0].get("text", "") == "":
                    return True
        return False

    def validate(self, data):
        request = self.context["request"]
        instance = cast(Comment, self.instance)

        if instance:
            if instance.created_by != request.user:
                raise exceptions.PermissionDenied("You can only modify your own comments")

        content = data.get("content", "")
        rich_content = data.get("rich_content")

        if not content.strip() and (not rich_content or self.has_empty_paragraph(rich_content)):
            raise exceptions.ValidationError("A comment must have content")

        data["created_by"] = request.user

        return data

    def _send_mention_notifications(self, comment: Comment, mentioned_user_ids: list[int], slug: str) -> None:
        """
        Send in-app notifications to users mentioned in a comment.

        Args:
            comment: The comment instance
            mentioned_user_ids: List of user IDs that were mentioned
            slug: URL slug for the resource being commented on
        """
        from posthog.notifications.producer import broadcast_notification

        if not mentioned_user_ids:
            return

        # Build notification message
        author_name = comment.created_by.first_name or comment.created_by.email

        # Determine what was commented on
        resource_name = self._get_resource_name_from_scope(comment.scope)

        # Get a preview of the comment (first 100 chars)
        comment_preview = (comment.content or "")[:100]
        if len(comment.content or "") > 100:
            comment_preview += "..."

        # Build context with all relevant information
        context = {
            "comment_id": str(comment.id),
            "author_id": comment.created_by_id,
            "author_name": author_name,
            "comment_preview": comment_preview,
            "scope": comment.scope,
            "item_id": comment.item_id,
            "slug": slug,
            "is_reply": comment.source_comment_id is not None,
        }

        # Send notification to each mentioned user
        for user_id in mentioned_user_ids:
            broadcast_notification(
                team_id=comment.team_id,
                user_id=user_id,  # Direct to specific user
                resource_type="mention",
                event_type="created",
                title=f"{author_name} mentioned you",
                message=f'{author_name} mentioned you in a comment on {resource_name}: "{comment_preview}"',
                resource_id=str(comment.id),
                context=context,
            )

    def _get_resource_name_from_scope(self, scope: str) -> str:
        """Convert scope to user-friendly resource name."""
        scope_map = {
            "Insight": "an insight",
            "FeatureFlag": "a feature flag",
            "Dashboard": "a dashboard",
            "Replay": "a replay",
            "Comment": "a comment thread",
            "Notebook": "a notebook",
        }
        return scope_map.get(scope, f"a {scope.lower()}")

    def create(self, validated_data: Any) -> Any:
        mentions: list[int] = validated_data.pop("mentions", [])
        slug: str = validated_data.pop("slug", "")
        validated_data["team_id"] = self.context["team_id"]

        comment = super().create(validated_data)

        if mentions:
            send_discussions_mentioned.delay(comment.id, mentions, slug)

            # Send in-app notifications to mentioned users
            self._send_mention_notifications(comment, mentions, slug)

        return comment

    def update(self, instance: Comment, validated_data: dict, **kwargs) -> Comment:
        mentions: list[int] = validated_data.pop("mentions", [])
        slug: str = validated_data.pop("slug", "")
        request = self.context["request"]

        with transaction.atomic():
            # select_for_update locks the database row so we ensure version updates are atomic
            locked_instance = Comment.objects.select_for_update().get(pk=instance.pk)

            if locked_instance.created_by != request.user:
                raise

            if validated_data.keys():
                if validated_data.get("content"):
                    validated_data["version"] = locked_instance.version + 1

                updated_instance = super().update(locked_instance, validated_data)

        if mentions:
            send_discussions_mentioned.delay(updated_instance.id, mentions, slug)

            # Send in-app notifications to mentioned users
            self._send_mention_notifications(updated_instance, mentions, slug)

        return updated_instance


class CommentPagination(pagination.CursorPagination):
    ordering = "-created_at"
    page_size = 100


class CommentViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    pagination_class = CommentPagination
    # TODO: Update when fully released
    scope_object = "INTERNAL"

    def safely_get_queryset(self, queryset) -> QuerySet:
        params = self.request.GET.dict()

        if params.get("user"):
            queryset = queryset.filter(user=params.get("user"))

        if self.action != "partial_update" and params.get("deleted", "false") == "false":
            queryset = queryset.filter(deleted=False)

        if params.get("scope"):
            queryset = queryset.filter(scope=params.get("scope"))

        if params.get("item_id"):
            queryset = queryset.filter(item_id=params.get("item_id"))

        if params.get("search"):
            queryset = queryset.filter(content__search=params.get("search"))

        if params.get("exclude_emoji_reactions") == "true":
            queryset = queryset.filter(
                Q(item_context__isnull=True) | ~Q(item_context__has_key="is_emoji") | Q(item_context__is_emoji=False)
            )

        source_comment = params.get("source_comment")
        if self.action == "thread":
            # Filter based on the source_comment
            source_comment = self.kwargs.get("pk")

        if source_comment:
            # NOTE: Should we also return the source_comment ?
            queryset = queryset.filter(source_comment_id=source_comment)

        return queryset

    @action(methods=["GET"], detail=True)
    def thread(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.list(request, *args, **kwargs)

    @action(methods=["GET"], detail=False)
    def count(self, request: Request, **kwargs) -> Response:
        queryset = self.get_queryset()
        count = queryset.count()

        return Response({"count": count})
