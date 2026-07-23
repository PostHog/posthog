from datetime import timedelta
from typing import Any, cast

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

import structlog
import posthoganalytics
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import exceptions, pagination, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from slack_sdk.errors import SlackApiError

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import ClassicBehaviorBooleanFieldSerializer, action
from posthog.exceptions import Conflict
from posthog.helpers.slack_thread_mirror import post_comment_to_slack_thread, slack_author_from_user
from posthog.models import User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.activity_logging.model_activity import get_was_impersonated
from posthog.models.comment import Comment, CommentSlackThread
from posthog.models.comment.comment import TICKET_COMMENT_SCOPES, activity_log_scope_for
from posthog.models.comment.slack_thread import DISCUSSIONS_SLACK_SYNC_FLAG
from posthog.models.comment.utils import (
    build_comment_item_url,
    comment_scope_display_name,
    produce_discussion_mention_events,
    send_mention_notifications,
)
from posthog.models.integration import Integration, SlackIntegration
from posthog.tasks.comment_slack_sync import backfill_comment_slack_thread
from posthog.tasks.email import send_discussions_mentioned

logger = structlog.get_logger(__name__)

# A reservation with no posted root older than this is a crashed send — safe to retry.
STALE_SLACK_RESERVATION_GRACE = timedelta(minutes=2)

# item_context keys the Slack mirror sync stamps server-side. Stripped from client input so a
# caller can't forge sync state (suppress mirroring of a reply, or spoof Slack attribution).
RESERVED_ITEM_CONTEXT_KEYS = frozenset({"from_slack", "slack_synced_ts"})


def _release_slack_reservation(slack_thread: "CommentSlackThread") -> None:
    """Best-effort release so a later send can retry; must not mask the Slack error being raised."""
    try:
        slack_thread.delete()
    except Exception:
        # The stale-reservation grace period will unblock a retry even if this row lingers.
        logger.exception("comment_slack_reservation_release_failed", slack_thread_id=str(slack_thread.id))


def _slack_thread_url(thread: CommentSlackThread) -> str:
    """Permalink that opens the mirrored Slack thread.

    Uses the standard `/archives/<channel>/p<ts>` permalink form (ts with the dot removed); Slack
    resolves the workspace from the channel. Falls back to the channel if the root isn't posted yet.
    """
    base = f"https://app.slack.com/archives/{thread.slack_channel_id}"
    if not thread.slack_thread_ts:
        return base
    return f"{base}/p{thread.slack_thread_ts.replace('.', '')}"


class CommentSlackThreadRefSerializer(serializers.Serializer):
    channel_id = serializers.CharField(help_text="Slack channel ID this discussion is mirrored to.")
    url = serializers.CharField(help_text="Deep link that opens the mirrored Slack thread.")


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
    slack_thread = serializers.SerializerMethodField(
        help_text=(
            "The Slack thread this comment's discussion is mirrored to, or null. Set only on a "
            "tracked thread-root comment; used to surface an 'Open in Slack' link and hide re-sending."
        )
    )

    @extend_schema_field(CommentSlackThreadRefSerializer(allow_null=True))
    def get_slack_thread(self, comment: Comment) -> dict | None:
        by_comment = self.context.get("slack_thread_by_comment") or {}
        thread = by_comment.get(str(comment.id))
        # A reservation with no posted root isn't a live mirror — report null so the UI
        # keeps offering "send to Slack" rather than a dead "Open in Slack" link.
        if thread is None or not thread.slack_thread_ts:
            return None
        return {"channel_id": thread.slack_channel_id, "url": _slack_thread_url(thread)}

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

        if isinstance(data.get("item_context"), dict):
            data["item_context"] = {
                k: v for k, v in data["item_context"].items() if k not in RESERVED_ITEM_CONTEXT_KEYS
            }

        if not instance:
            data["created_by"] = request.user
            if data.get("is_task"):
                if data.get("source_comment"):
                    raise exceptions.ValidationError({"is_task": "Replies cannot be tasks."})
                item_context = data.get("item_context") or {}
                if item_context.get("is_emoji"):
                    raise exceptions.ValidationError({"is_task": "Emoji reactions cannot be tasks."})

        # A reply lives in its parent's thread: a scope mismatch would let content cross the
        # authorization boundary between ticket and non-ticket discussions in either direction.
        source_comment = (
            data["source_comment"] if "source_comment" in data else getattr(instance, "source_comment", None)
        )
        scope = data["scope"] if "scope" in data else getattr(instance, "scope", None)
        if source_comment is not None:
            if source_comment.team_id != self.context["team_id"]:
                raise exceptions.ValidationError({"source_comment": "Comment not found."})
            if source_comment.scope != scope:
                raise exceptions.ValidationError(
                    {"scope": "A reply must use the same scope as the comment it replies to."}
                )

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
        help_text=(
            "Filter by resource type (e.g. Dashboard, FeatureFlag, Insight, Replay). "
            "Support-ticket scopes (Ticket, conversations_ticket) additionally require ticket API scope access."
        ),
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


class CommentSlackThreadSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(
        read_only=True, allow_null=True, help_text="User who mirrored the discussion. Null if since deleted."
    )

    class Meta:
        model = CommentSlackThread
        fields = [
            "id",
            "scope",
            "item_id",
            "source_comment",
            "integration",
            "slack_channel_id",
            "slack_thread_ts",
            "slack_team_id",
            "created_at",
            "created_by",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "scope": {"help_text": "Resource type of the mirrored discussion (e.g. Insight)."},
            "item_id": {"help_text": "ID of the resource the discussion is attached to."},
            "source_comment": {"help_text": "The thread-root comment whose replies mirror to the Slack thread."},
            "integration": {"help_text": "Slack integration used to post to and read from the thread."},
            "slack_channel_id": {"help_text": "Slack channel the mirrored thread lives in."},
            "slack_thread_ts": {"help_text": "Slack thread timestamp anchoring the mirrored thread."},
            "slack_team_id": {"help_text": "Slack workspace ID, used to route inbound replies back."},
        }


class SendCommentToSlackSerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(
        help_text="ID of the Slack integration (kind='slack') whose bot posts the thread."
    )
    channel_id = serializers.CharField(
        max_length=255,
        help_text="Slack channel ID to create the mirrored thread in. The bot must be a member of the channel.",
    )


@extend_schema(extensions={"x-product": "platform_features"})
class CommentViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    pagination_class = CommentPagination
    scope_object = "comment"
    scope_object_read_actions = ["list", "retrieve", "thread", "count"]

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        """Ticket-scoped comments require ticket API scope access instead of comment access.

        Candidate scopes are the union of every scope that determines what the request can
        read or write: the query-param scope (the queryset always filters by it, including for
        detail lookups and /thread), the stored scope of the pk target (authoritative — a
        mismatched body scope can't sidestep it), and the body scope on writes only (what
        create writes and update can rewrite; a body on a GET selects nothing). If any
        candidate is ticket-carrying the request needs ticket access, and any non-ticket
        candidate keeps the default comment requirement alongside it (the scopes are ANDed).
        """
        candidate_scopes: set[Any] = set()
        if query_scope := request.GET.get("scope"):
            candidate_scopes.add(query_scope)
        if pk := self.kwargs.get("pk"):
            try:
                candidate_scopes.add(
                    Comment.objects.filter(team_id=self.team_id, pk=pk).values_list("scope", flat=True).first()
                )
            except (ValueError, ValidationError):
                return None
        if request.method not in ("GET", "HEAD", "OPTIONS") and isinstance(request.data, dict):
            if body_scope := request.data.get("scope"):
                candidate_scopes.add(body_scope)
            # A reply is read back through its parent's thread, so the parent's stored scope
            # gates the write too — a non-ticket body scope must not attach a reply to a
            # ticket thread (nor a ticket reply to a non-ticket parent).
            if source_comment := request.data.get("source_comment"):
                try:
                    candidate_scopes.add(
                        Comment.objects.filter(team_id=self.team_id, pk=source_comment)
                        .values_list("scope", flat=True)
                        .first()
                    )
                except (ValueError, ValidationError):
                    return None
        candidate_scopes.discard(None)
        if not candidate_scopes & TICKET_COMMENT_SCOPES:
            return None
        access = "read" if self.action in self.scope_object_read_actions else "write"
        required: list[str] = [f"ticket:{access}"]
        if candidate_scopes - TICKET_COMMENT_SCOPES:
            required.append(f"comment:{access}")
        return required

    @extend_schema(parameters=[CommentListQueryParamsSerializer])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def _slack_mirror_flag_enabled(self) -> bool:
        """Whether discussions↔Slack sync is on for this user/team.

        Keyed on the requesting user (plus org/project groups) so the gate agrees with the
        frontend's per-user flag evaluation during partial rollouts.
        """
        team = self.team
        flag_distinct_id = str(getattr(self.request.user, "distinct_id", None) or team.uuid)
        try:
            return bool(
                posthoganalytics.feature_enabled(
                    DISCUSSIONS_SLACK_SYNC_FLAG,
                    flag_distinct_id,
                    groups={"organization": str(team.organization_id), "project": str(team.id)},
                )
            )
        except Exception:
            return False

    def get_serializer_context(self) -> dict:
        context = super().get_serializer_context()
        # Prefetch the discussion's Slack mirrors once (keyed by thread-root comment, 1:1) so the
        # serializer's slack_thread field doesn't do a query per comment. Skipped entirely while
        # the feature flag is off, so unflagged teams don't pay the lookup on a hot endpoint.
        scope = self.request.GET.get("scope")
        item_id = self.request.GET.get("item_id")
        pk = self.kwargs.get("pk")
        thread_by_comment: dict[str, CommentSlackThread] = {}
        if ((scope and item_id) or pk) and self._slack_mirror_flag_enabled():
            if scope and item_id:
                for thread in CommentSlackThread.objects.for_team(self.team.id).filter(scope=scope, item_id=item_id):
                    if thread.source_comment_id:
                        thread_by_comment[str(thread.source_comment_id)] = thread
            else:
                # Detail responses (retrieve/update/complete/reopen) have no scope/item_id params; fetch
                # the one possible mirror so slack_thread doesn't silently null out — the frontend
                # replaces list entries with these responses, which would drop the Slack state.
                for thread in CommentSlackThread.objects.for_team(self.team.id).filter(source_comment_id=pk):
                    thread_by_comment[str(thread.source_comment_id)] = thread
        context["slack_thread_by_comment"] = thread_by_comment
        return context

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        params = self.request.GET.dict()

        if params.get("user"):
            queryset = queryset.filter(user=params.get("user"))

        if self.action != "partial_update" and params.get("deleted", "false") == "false":
            queryset = queryset.filter(deleted=False)

        if params.get("scope"):
            queryset = queryset.filter(scope=params.get("scope"))
        elif self.action in ("list", "count"):
            # Ticket-carrying comments (customer messages and internal ticket discussions) never
            # appear in unscoped enumeration — only when explicitly requested by scope. Detail
            # actions (retrieve, thread, send_to_slack, ...) pin an object by pk, where ticket
            # API scope access is enforced by dangerously_get_required_scopes instead.
            queryset = queryset.exclude(scope__in=TICKET_COMMENT_SCOPES)

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

    @extend_schema(
        request=SendCommentToSlackSerializer,
        responses=CommentSlackThreadSerializer,
        description=(
            "Mirror this discussion thread to a Slack channel. Posts the comment (and its existing "
            "replies) as a new Slack thread; later replies on either side sync across. A discussion "
            "mirrors to exactly one Slack thread: re-calling with the same channel returns the "
            "existing mirror; a different channel is a 400 naming the existing one. 409 while a "
            "concurrent send is in flight. 404 when the feature is not enabled for the team."
        ),
    )
    @action(methods=["POST"], detail=True)
    def send_to_slack(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        team = self.team
        if not self._slack_mirror_flag_enabled():
            raise exceptions.NotFound()

        comment = self.get_object()
        if comment.source_comment_id is not None:
            raise exceptions.ValidationError("Only a top-level comment (a thread root) can be sent to Slack")
        if comment.scope == "conversations_ticket":
            raise exceptions.ValidationError("Conversations tickets sync to Slack through the support product")

        params = SendCommentToSlackSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        integration_id = params.validated_data["integration_id"]
        channel_id = params.validated_data["channel_id"]

        integration = Integration.objects.filter(team=team, id=integration_id, kind="slack").first()
        if integration is None:
            raise exceptions.ValidationError("Slack integration not found")

        # Reserve the mapping before posting: a discussion mirrors to exactly one Slack thread (1:1),
        # and the source_comment OneToOne makes this get_or_create race-safe — a double-click can't
        # post two root messages.
        slack_thread, created = CommentSlackThread.objects.for_team(team.id).get_or_create(
            team=team,
            source_comment=comment,
            defaults={
                "scope": comment.scope,
                "item_id": comment.item_id,
                "integration": integration,
                "slack_channel_id": channel_id,
                "slack_team_id": integration.integration_id,
                "created_by": cast(User, request.user),
            },
        )
        if not created:
            if slack_thread.slack_thread_ts:
                if slack_thread.slack_channel_id != channel_id:
                    raise exceptions.ValidationError(
                        "This discussion is already mirrored to Slack channel "
                        f"{slack_thread.slack_channel_id} — a discussion can only sync to one thread"
                    )
                # Idempotent: already mirrored to this channel — return the mapping, no re-post.
                return Response(CommentSlackThreadSerializer(slack_thread).data)
            if timezone.now() - slack_thread.created_at < STALE_SLACK_RESERVATION_GRACE:
                # Another request holds the reservation and its root post is still in flight.
                raise Conflict("This discussion is already being sent to Slack — try again shortly")
            # A reservation this old with no root message is a crashed send that would otherwise
            # block the discussion forever. Adopt it and retry the post; resetting created_at
            # re-bounds the reply backfill to this attempt.
            slack_thread.integration = integration
            slack_thread.slack_channel_id = channel_id
            slack_thread.slack_team_id = integration.integration_id
            slack_thread.created_by = cast(User, request.user)
            slack_thread.created_at = timezone.now()
            slack_thread.save(
                update_fields=["integration", "slack_channel_id", "slack_team_id", "created_by", "created_at"]
            )

        author_name, author_email = slack_author_from_user(comment.created_by)
        client = SlackIntegration(integration).client
        client.timeout = 10  # keep a slow Slack workspace from pinning the request worker
        try:
            thread_ts = post_comment_to_slack_thread(
                client=client,
                channel=channel_id,
                content=comment.content or "",
                rich_content=comment.rich_content,
                author_name=author_name,
                author_email=author_email,
                item_url=build_comment_item_url(comment.scope, comment.item_id),
                item_label=comment_scope_display_name(comment.scope),
            )
        except Exception as e:
            _release_slack_reservation(slack_thread)
            # Surface Slack's error code (not_in_channel, channel_not_found, ...) — it's the
            # actionable part for the user; the full exception is chained for error tracking.
            slack_error = e.response.get("error") if isinstance(e, SlackApiError) and e.response else None
            detail = (
                f"Failed to post the discussion to Slack ({slack_error})"
                if slack_error
                else ("Failed to post the discussion to Slack")
            )
            raise exceptions.ValidationError(detail) from e
        if not thread_ts:
            _release_slack_reservation(slack_thread)
            raise exceptions.ValidationError("Cannot send an empty comment to Slack")

        slack_thread.slack_thread_ts = thread_ts
        slack_thread.save(update_fields=["slack_thread_ts"])

        # Backfill existing replies asynchronously so the request isn't blocked on N Slack posts.
        backfill_comment_slack_thread.delay(comment_slack_thread_id=str(slack_thread.id))

        return Response(CommentSlackThreadSerializer(slack_thread).data)

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
