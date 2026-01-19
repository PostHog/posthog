from typing import Any, cast

from django.db import transaction
from django.db.models import Q, QuerySet

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, pagination, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import ClassicBehaviorBooleanFieldSerializer, action
from posthog.models.comment import Comment
from posthog.tasks.email import send_discussions_mentioned

logger = structlog.get_logger(__name__)


class CommentSerializer(serializers.ModelSerializer):
    def _extract_mentions_from_rich_content(self, rich_content: dict | None) -> list[int]:
        """Extract user IDs from ph-mention nodes in rich_content"""
        if not rich_content:
            return []

        mentions = []

        def find_mentions(node):
            if isinstance(node, dict):
                if node.get("type") == "ph-mention":
                    user_id = node.get("attrs", {}).get("id")
                    if user_id and isinstance(user_id, int) and user_id not in mentions:
                        mentions.append(user_id)
                for value in node.values():
                    if isinstance(value, (dict, list)):
                        find_mentions(value)
            elif isinstance(node, list):
                for item in node:
                    find_mentions(item)

        find_mentions(rich_content)
        return mentions

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

    def create(self, validated_data: Any) -> Any:
        mentions: list[int] = validated_data.pop("mentions", [])

        # Extract mentions from rich_content if not provided explicitly
        if not mentions:
            mentions = self._extract_mentions_from_rich_content(validated_data.get("rich_content"))

        slug: str = validated_data.pop("slug", "")
        validated_data["team_id"] = self.context["team_id"]

        comment = super().create(validated_data)

        if mentions:
            logger.info(f"Sending discussions mentioned email for comment {comment.id} to {mentions}")
            send_discussions_mentioned.delay(comment.id, mentions, slug)

        return comment

    def update(self, instance: Comment, validated_data: dict, **kwargs) -> Comment:
        mentions: list[int] = validated_data.pop("mentions", [])

        # Extract mentions from rich_content if not provided explicitly
        if not mentions:
            mentions = self._extract_mentions_from_rich_content(validated_data.get("rich_content"))

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

        return updated_instance


class CommentPagination(pagination.CursorPagination):
    ordering = "-created_at"
    page_size = 100


@extend_schema(tags=["core"])
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
