from typing import Any, cast

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, pagination, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import ClassicBehaviorBooleanFieldSerializer, action
from posthog.models import User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.activity_logging.model_activity import get_was_impersonated
from posthog.models.comment import Comment
from posthog.models.comment.comment import activity_log_scope_for
from posthog.models.comment.utils import produce_discussion_mention_events, send_mention_notifications
from posthog.tasks.email import send_discussions_mentioned


class CommentSerializer(serializers.ModelSerializer):
    def _extract_mentions_from_rich_content(self, rich_content: dict | None) -> list[int]:
        if not rich_content:
            return []

        mentions: list[int] = []

        def find_mentions(node: Any) -> None:
            if isinstance(node, dict):
                if node.get("type") == "ph-mention":
                    user_id = node.get("attrs", {}).get("id")
                    if user_id and isinstance(user_id, int) and user_id not in mentions:
                        mentions.append(user_id)
                for value in node.values():
                    if isinstance(value, dict | list):
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
    is_task = serializers.BooleanField(
        default=False,
        required=False,
        help_text=(
            "Whether this comment is an actionable task that can be marked complete. "
            "Tasks render with a checkbox in the UI and can be filtered as a separate kind. "
            "Cannot be set on replies (source_comment) or emoji reactions. Immutable after creation."
        ),
    )
    completed_by = UserBasicSerializer(
        read_only=True,
        allow_null=True,
        help_text="The user who marked this task complete. Null for open tasks and non-task comments.",
    )

    class Meta:
        model = Comment
        exclude = ["team"]
        read_only_fields = ["id", "created_by", "version", "completed_at", "completed_by"]
        extra_kwargs = {
            "completed_at": {
                "help_text": (
                    "ISO timestamp when the task was marked complete. Only meaningful when is_task is true. "
                    "Read-only — toggled via the /complete and /reopen actions, not via PATCH."
                ),
            },
        }

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Coerce legacy null is_task rows to False so the contract stays non-null.
        if data.get("is_task") is None:
            data["is_task"] = False
        return data

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
            if "is_task" in data and bool(data["is_task"]) != bool(instance.is_task):
                raise exceptions.ValidationError({"is_task": "Cannot change task state after creation."})

        # Skip content validation when soft-deleting a comment
        is_deleting = data.get("deleted") is True
        if not is_deleting:
            content = data.get("content", "")
            rich_content = data.get("rich_content")

            if not content.strip() and (not rich_content or self.has_empty_paragraph(rich_content)):
                raise exceptions.ValidationError("A comment must have content")

        if not instance:
            data["created_by"] = request.user
            if data.get("is_task"):
                if data.get("source_comment"):
                    raise exceptions.ValidationError({"is_task": "Replies cannot be tasks."})
                item_context = data.get("item_context") or {}
                if item_context.get("is_emoji"):
                    raise exceptions.ValidationError({"is_task": "Emoji reactions cannot be tasks."})

        return data

    def _filter_mentions_to_organization(self, mention_ids: list[int], organization_id: str) -> list[int]:
        if not mention_ids:
            return []
        valid_ids = set(
            User.objects.filter(
                id__in=mention_ids,
                organization_membership__organization_id=organization_id,
            ).values_list("id", flat=True)
        )
        return [uid for uid in mention_ids if uid in valid_ids]

    def create(self, validated_data: Any) -> Any:
        mentions: list[int] = validated_data.pop("mentions", [])

        if not mentions:
            mentions = self._extract_mentions_from_rich_content(validated_data.get("rich_content"))

        slug: str = validated_data.pop("slug", "")
        validated_data["team_id"] = self.context["team_id"]

        mentions = self._filter_mentions_to_organization(mentions, self.context["get_organization"]().id)

        comment = super().create(validated_data)

        if mentions:
            send_discussions_mentioned.delay(comment.id, mentions, slug)
            produce_discussion_mention_events(comment, mentions, slug)
            send_mention_notifications(comment, mentions, slug)

        return comment

    def update(self, instance: Comment, validated_data: dict, **kwargs: Any) -> Comment:
        mentions: list[int] = validated_data.pop("mentions", [])

        if not mentions:
            mentions = self._extract_mentions_from_rich_content(validated_data.get("rich_content"))

        slug: str = validated_data.pop("slug", "")
        request = self.context["request"]

        mentions = self._filter_mentions_to_organization(mentions, self.context["get_organization"]().id)

        with transaction.atomic():
            locked_instance = Comment.objects.select_for_update().get(pk=instance.pk)

            if locked_instance.created_by != request.user:
                raise

            if validated_data.keys():
                if validated_data.get("content"):
                    validated_data["version"] = locked_instance.version + 1

                updated_instance = super().update(locked_instance, validated_data)

        if mentions:
            send_discussions_mentioned.delay(updated_instance.id, mentions, slug)
            produce_discussion_mention_events(updated_instance, mentions, slug)
            send_mention_notifications(updated_instance, mentions, slug)

        return updated_instance


class CommentPagination(pagination.CursorPagination):
    ordering = "-created_at"
    page_size = 100


class CommentListQueryParamsSerializer(serializers.Serializer):
    scope = serializers.CharField(
        required=False,
        help_text="Filter by resource type (e.g. Dashboard, FeatureFlag, Insight, Replay).",
    )
    item_id = serializers.CharField(required=False, help_text="Filter by the ID of the resource being commented on.")
    search = serializers.CharField(required=False, help_text="Full-text search within comment content.")
    source_comment = serializers.CharField(required=False, help_text="Filter replies to a specific parent comment.")
    kind = serializers.ChoiceField(
        required=False,
        choices=["any", "comment", "task"],
        help_text=(
            "Filter by comment kind. 'task' returns only items intentionally created as actionable. "
            "'comment' excludes tasks. Defaults to 'any' (no filter)."
        ),
    )
    completed = serializers.ChoiceField(
        required=False,
        choices=["any", "open", "completed"],
        help_text=(
            "When kind=task, restrict to open (incomplete) or completed tasks. "
            "Ignored when kind is not 'task'. Defaults to 'any' (no filter)."
        ),
    )


@extend_schema(tags=["core", "platform_features"])
class CommentViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    pagination_class = CommentPagination
    scope_object = "comment"
    scope_object_read_actions = ["list", "retrieve", "thread", "count"]

    @extend_schema(parameters=[CommentListQueryParamsSerializer])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        params = self.request.GET.dict()

        if params.get("user"):
            queryset = queryset.filter(user=params.get("user"))

        if self.action != "partial_update" and params.get("deleted", "false") == "false":
            queryset = queryset.filter(deleted=False)

        if params.get("scope"):
            queryset = queryset.filter(scope=params.get("scope"))
        else:
            # Exclude conversations_ticket comments by default - they use rich content
            # from SupportEditor and should only be viewed in the conversations product
            queryset = queryset.exclude(scope="conversations_ticket")

        if params.get("item_id"):
            queryset = queryset.filter(item_id=params.get("item_id"))

        if params.get("search"):
            queryset = queryset.filter(content__search=params.get("search"))

        if params.get("exclude_emoji_reactions") == "true":
            queryset = queryset.filter(
                Q(item_context__isnull=True) | ~Q(item_context__has_key="is_emoji") | Q(item_context__is_emoji=False)
            )

        kind = params.get("kind")
        if kind == "task":
            queryset = queryset.filter(is_task=True)
        elif kind == "comment":
            # Pre-migration rows have is_task=NULL; count them as comments.
            queryset = queryset.filter(Q(is_task=False) | Q(is_task__isnull=True))

        if kind == "task":
            completed = params.get("completed")
            if completed == "open":
                queryset = queryset.filter(completed_at__isnull=True)
            elif completed == "completed":
                queryset = queryset.filter(completed_at__isnull=False)

        source_comment = params.get("source_comment")
        if self.action == "thread":
            source_comment = self.kwargs.get("pk")

        if source_comment:
            queryset = queryset.filter(source_comment_id=source_comment)

        return queryset

    @action(methods=["GET"], detail=True)
    def thread(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.list(request, *args, **kwargs)

    @action(methods=["GET"], detail=False)
    def count(self, request: Request, **kwargs: Any) -> Response:
        queryset = self.get_queryset()
        count = queryset.count()

        return Response({"count": count})

    @extend_schema(
        request=None,
        responses=CommentSerializer,
        description="Mark a task-comment as complete. Sets completed_at and completed_by. "
        "400 if the comment is not a task or is already complete.",
    )
    @action(methods=["POST"], detail=True)
    def complete(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        comment = self.get_object()
        if not comment.is_task:
            raise exceptions.ValidationError("Only tasks can be marked complete")
        with transaction.atomic():
            comment = Comment.objects.select_for_update().get(pk=comment.pk)
            if comment.completed_at is not None:
                raise exceptions.ValidationError("Task is already complete")
            comment.completed_at = timezone.now()
            comment.completed_by = cast(User, request.user)
            comment.save(update_fields=["completed_at", "completed_by"])
            self._log_task_state_change(comment, request, completed=True)
        serializer = CommentSerializer(comment, context=self.get_serializer_context())
        return Response(serializer.data)

    @extend_schema(
        request=None,
        responses=CommentSerializer,
        description="Reopen a completed task-comment. Clears completed_at and completed_by. "
        "400 if the comment is not a task or is already open.",
    )
    @action(methods=["POST"], detail=True)
    def reopen(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        comment = self.get_object()
        if not comment.is_task:
            raise exceptions.ValidationError("Only tasks can be reopened")
        with transaction.atomic():
            comment = Comment.objects.select_for_update().get(pk=comment.pk)
            if comment.completed_at is None:
                raise exceptions.ValidationError("Task is already open")
            comment.completed_at = None
            comment.completed_by = None
            comment.save(update_fields=["completed_at", "completed_by"])
            self._log_task_state_change(comment, request, completed=False)
        serializer = CommentSerializer(comment, context=self.get_serializer_context())
        return Response(serializer.data)

    @staticmethod
    def _log_task_state_change(comment: Comment, request: Request, *, completed: bool) -> None:
        log_activity(
            organization_id=None,
            team_id=comment.team_id,
            user=cast(User, request.user),
            was_impersonated=get_was_impersonated(),
            item_id=cast(str, comment.source_comment_id) or comment.item_id,
            scope=activity_log_scope_for(comment),
            activity="completed task" if completed else "reopened task",
            detail=Detail(
                changes=[
                    Change(
                        type="Comment",
                        field="completed_at",
                        action="changed",
                        before=None if completed else "completed",
                        after="completed" if completed else None,
                    )
                ],
            ),
        )
