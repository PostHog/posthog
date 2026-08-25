from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from django.core import exceptions as django_exceptions
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

import structlog
import posthoganalytics
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import exceptions, pagination, serializers, status, viewsets
from rest_framework.exceptions import ErrorDetail
from rest_framework.generics import get_object_or_404
from rest_framework.request import Request
from rest_framework.response import Response
from slack_sdk.errors import SlackApiError

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import ClassicBehaviorBooleanFieldSerializer, action
from posthog.comment.access import task_comment_target_is_accessible
from posthog.event_usage import groups
from posthog.exceptions import Conflict
from posthog.helpers.slack_thread_mirror import post_comment_to_slack_thread, slack_author_from_user
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.activity_logging.model_activity import get_was_impersonated
from posthog.models.comment import Comment, CommentSlackThread
from posthog.models.comment.comment import (
    COMMENT_SCOPES_BLOCKED_FROM_GENERIC_API,
    TICKET_COMMENT_SCOPES,
    activity_log_scope_for,
)
from posthog.models.comment.slack_thread import DISCUSSIONS_SLACK_SYNC_FLAG
from posthog.models.comment.utils import (
    DESKTOP_COMMENT_SCOPES,
    build_comment_item_url,
    comment_scope_display_name,
    produce_discussion_mention_events,
    send_mention_notifications,
)
from posthog.models.integration import Integration, SlackIntegration
from posthog.tasks.comment_slack_sync import backfill_comment_slack_thread
from posthog.tasks.email import send_discussions_mentioned

from products.conversations.backend import reply_dedupe

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl

logger = structlog.get_logger(__name__)


def _normalize_scope(scope: Any) -> Any:
    """Match how the serializer will store a submitted scope.

    `scope` is a CharField, so DRF trims surrounding whitespace before saving — comparing the
    raw value here would let " Ticket " read as non-ticket while persisting as "Ticket".
    """
    return scope.strip() if isinstance(scope, str) else scope


def _require_ticket_editor_access(
    *, team_id: int, item_id: str | None, user_access_control: "UserAccessControl"
) -> None:
    """Ticket-carrying comments (customer messages and internal ticket discussions) are ticket
    content (see TicketViewSet.reply) — enforce the same object-level RBAC here, since the generic
    comments API is the write path the Support UI actually uses and isn't gated by TicketViewSet's
    own access control."""
    if not item_id:
        return

    from products.conversations.backend.models.ticket import (  # noqa: PLC0415 — keeps the generic comments API decoupled from the conversations product, only imported for ticket-scoped writes
        Ticket,
    )

    try:
        ticket = Ticket.objects.get(team_id=team_id, id=item_id)
    except (Ticket.DoesNotExist, ValueError, django_exceptions.ValidationError):
        raise exceptions.ValidationError({"item_id": "Ticket not found"})

    if not user_access_control.check_access_level_for_object(ticket, required_level="editor"):
        raise exceptions.PermissionDenied("You do not have access to this ticket")


# A reservation with no posted root older than this is a crashed send — safe to retry.
STALE_SLACK_RESERVATION_GRACE = timedelta(minutes=2)

# item_context keys the Slack mirror sync stamps server-side. Stripped from client input so a
# caller can't forge sync state (suppress mirroring of a reply, block ingestion of a real Slack
# message by squatting on its ts, or spoof a Slack author identity in the discussion UI).
RESERVED_ITEM_CONTEXT_KEYS = frozenset(
    {"from_slack", "slack_synced_ts", "slack_message_ts", "slack_author_name", "slack_author_avatar"}
)


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
    channel_name = serializers.CharField(
        allow_blank=True,
        help_text="Slack channel name resolved from Slack when the discussion was sent (no leading #). "
        "Empty for private channels and when unknown; may lag behind a rename in Slack.",
    )
    url = serializers.CharField(help_text="Deep link that opens the mirrored Slack thread.")


def _capture_task_comment_action(comment: Comment, mentions: list[int], team: Team) -> None:
    if comment.scope not in DESKTOP_COMMENT_SCOPES or not comment.created_by or not comment.created_by.distinct_id:
        return

    context = comment.item_context if isinstance(comment.item_context, dict) else {}
    thread_state = context.get("threadState")
    if comment.source_comment_id and thread_state == "resolved":
        action_type = "resolved"
    elif comment.source_comment_id and thread_state == "open":
        action_type = "reopened"
    elif comment.source_comment_id:
        action_type = "replied"
    else:
        action_type = "created"

    anchor = context.get("anchor")
    anchor_kind = anchor.get("kind") if isinstance(anchor, dict) else None
    raw_task_id = comment.item_id if comment.scope == "task" else context.get("taskId")
    properties: dict[str, Any] = {
        "analytics_version": 1,
        "action_type": action_type,
        "scope": comment.scope,
        "anchor_kind": anchor_kind if anchor_kind in {"text", "region", "document"} else "unknown",
        "task_id": raw_task_id if isinstance(raw_task_id, str) else None,
        "item_id": comment.item_id,
        "thread_id": str(comment.source_comment_id or comment.id),
        "comment_id": str(comment.id),
        "is_reply": action_type == "replied",
        "mention_count": len(mentions),
    }
    if action_type in {"created", "replied"}:
        content_length = len(comment.content or "")
        properties["content_length_bucket"] = (
            "0-50" if content_length <= 50 else "51-200" if content_length <= 200 else "201+"
        )
    if action_type in {"created", "reopened"}:
        properties["thread_state"] = "open"
    elif action_type == "resolved":
        properties["thread_state"] = "resolved"

    try:
        posthoganalytics.capture(
            distinct_id=str(comment.created_by.distinct_id),
            event="Comment action",
            properties=properties,
            groups=groups(team=team),
        )
    except Exception:
        logger.exception("Failed to capture task comment analytics", extra={"comment_id": str(comment.id)})


def _record_task_comment_activity(
    comment: Comment,
    mentions: list[int],
    *,
    activity_at: datetime | None = None,
    include_relationship_recipients: bool = True,
) -> None:
    if comment.scope not in DESKTOP_COMMENT_SCOPES:
        return

    owner_id = None
    try:
        from products.tasks.backend.facade.api import (  # noqa: PLC0415 — keeps the generic comments API decoupled from the tasks product
            record_comment_activity,
        )

        if comment.scope == "desktop_canvas" and comment.item_id:
            from products.canvas.backend.comment_access import canvas_owner_id  # noqa: PLC0415

            owner_id = canvas_owner_id(team_id=comment.team_id, canvas_id=comment.item_id)

        record_comment_activity(
            team_id=comment.team_id,
            comment_id=comment.id,
            mentioned_user_ids=mentions,
            include_relationship_recipients=include_relationship_recipients,
            target_owner_id=owner_id,
            activity_at=activity_at,
        )
    except Exception:
        logger.exception("Failed to project task comment activity", extra={"comment_id": str(comment.id)})
        from products.tasks.backend.facade.api import (  # noqa: PLC0415 — keeps the generic comments API decoupled from the tasks product
            enqueue_comment_activity_retry,
        )

        activity_at_value = activity_at.isoformat() if activity_at else None
        transaction.on_commit(
            lambda: enqueue_comment_activity_retry(
                team_id=comment.team_id,
                comment_id=str(comment.id),
                mentioned_user_ids=mentions,
                include_relationship_recipients=include_relationship_recipients,
                target_owner_id=owner_id,
                activity_at=activity_at_value,
            )
        )


def _mentions_allowed_for_comment_target(
    *, team_id: int, scope: str, item_id: str | None, item_context: dict | None
) -> bool:
    if scope not in DESKTOP_COMMENT_SCOPES:
        return True
    task_id = item_id if scope == "task" else (item_context or {}).get("taskId")
    if not task_id:
        return False
    from products.tasks.backend.facade.api import task_comment_mentions_allowed  # noqa: PLC0415

    return task_comment_mentions_allowed(team_id=team_id, task_id=task_id)


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

    created_by = UserBasicSerializer(read_only=True, allow_null=True)
    scope = serializers.CharField(required=False, max_length=79)
    item_context = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text="Metadata for the comment target, anchor, thread state, and owning task.",
    )
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
        return {
            "channel_id": thread.slack_channel_id,
            "channel_name": thread.slack_channel_name,
            "url": _slack_thread_url(thread),
        }

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

        item_context = data.get("item_context")
        if item_context is not None and not isinstance(item_context, dict):
            raise exceptions.ValidationError({"item_context": "Must be an object."})

        if instance:
            if instance.created_by != request.user:
                raise exceptions.PermissionDenied("You can only modify your own comments")
            if "is_task" in data and bool(data["is_task"]) != bool(instance.is_task):
                raise exceptions.ValidationError({"is_task": "Cannot change task state after creation."})

        # A reply lives in its parent's thread: a scope mismatch would let content cross the
        # authorization boundary between ticket and non-ticket discussions in either direction.
        source_comment = (
            data["source_comment"] if "source_comment" in data else getattr(instance, "source_comment", None)
        )
        if not instance and source_comment is None and "scope" not in data:
            raise exceptions.ValidationError({"scope": ErrorDetail("This field is required.", code="required")})
        scope = data["scope"] if "scope" in data else getattr(instance, "scope", None)
        item_id = data["item_id"] if "item_id" in data else getattr(instance, "item_id", None)
        candidate_scopes = {scope, getattr(instance, "scope", None), getattr(source_comment, "scope", None)}
        if candidate_scopes & COMMENT_SCOPES_BLOCKED_FROM_GENERIC_API:
            raise exceptions.PermissionDenied("Email thread messages cannot be managed through the comments API")
        if source_comment is not None:
            if source_comment.team_id != self.context["team_id"]:
                raise exceptions.ValidationError({"source_comment": "Comment not found."})
            if source_comment.scope != scope and (
                source_comment.scope in TICKET_COMMENT_SCOPES or scope in TICKET_COMMENT_SCOPES
            ):
                raise exceptions.ValidationError(
                    {"scope": "A reply must use the same scope as the comment it replies to."}
                )
            # /thread selects replies by source_comment_id alone, so a ticket reply carrying a
            # different item_id would render in a thread on a ticket its author never had to pass
            # the editor check for.
            if scope in TICKET_COMMENT_SCOPES and source_comment.item_id != item_id:
                raise exceptions.ValidationError(
                    {"item_id": "A reply must belong to the same ticket as the comment it replies to."}
                )

        # Check the comment's persisted (scope, item_id), the submitted target, and a reply's
        # parent — so losing ticket editor access after creation, re-scoping a comment into or out
        # of a ticket, and replying into a thread on another ticket are all caught, not just fresh
        # ticket-message creation.
        if not instance and source_comment is not None:
            root = source_comment.source_comment or source_comment
            data["source_comment"] = root
            data["scope"] = root.scope
            data["item_id"] = root.item_id
            reply_context = data.get("item_context") or {}
            root_context = root.item_context if isinstance(root.item_context, dict) else {}
            # Replies inherit the root's context (anchor, taskId) so filters keep
            # working, but a reply's own signal keys must survive the merge.
            data["item_context"] = {
                **{key: value for key, value in root_context.items() if key != "threadState"},
                **({"is_emoji": reply_context["is_emoji"]} if "is_emoji" in reply_context else {}),
                **(
                    {"threadState": reply_context["threadState"]}
                    if reply_context.get("threadState") in ("resolved", "open")
                    else {}
                ),
            }
            source_comment = root
            scope = root.scope
            item_id = root.item_id

        scopes_and_items = {(scope, item_id)}
        if instance:
            scopes_and_items.add((instance.scope, instance.item_id))
        if source_comment is not None:
            scopes_and_items.add((source_comment.scope, source_comment.item_id))
        for target_scope, target_item_id in scopes_and_items:
            if target_scope in TICKET_COMMENT_SCOPES:
                _require_ticket_editor_access(
                    team_id=self.context["get_team"]().id,
                    item_id=target_item_id,
                    user_access_control=self.context["get_user_access_control"](),
                )

        target_scope = data.get("scope", instance.scope if instance else None)
        target_item_id = data.get("item_id", instance.item_id if instance else None)
        target_context = data.get("item_context", instance.item_context if instance else None) or {}
        if target_scope in {"task", "task_artifact", "desktop_canvas"}:
            task_id = target_item_id if target_scope == "task" else target_context.get("taskId")
            if not task_comment_target_is_accessible(
                team_id=self.context["get_team"]().id,
                user_id=request.user.id,
                task_id=task_id or "",
                scope=target_scope,
                item_id=target_item_id,
            ):
                raise exceptions.PermissionDenied("You do not have access to this task comment target")

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
        if not _mentions_allowed_for_comment_target(
            team_id=self.context["team_id"],
            scope=validated_data["scope"],
            item_id=validated_data.get("item_id"),
            item_context=validated_data.get("item_context"),
        ):
            mentions = []

        comment = super().create(validated_data)

        if mentions:
            if comment.scope not in DESKTOP_COMMENT_SCOPES:
                send_discussions_mentioned.delay(comment.id, mentions, slug)
            produce_discussion_mention_events(comment, mentions, slug)
            send_mention_notifications(comment, mentions, slug)
        _record_task_comment_activity(comment, mentions)
        _capture_task_comment_action(comment, mentions, self.context["get_team"]())

        return comment

    def update(self, instance: Comment, validated_data: dict, **kwargs: Any) -> Comment:
        mentions: list[int] = validated_data.pop("mentions", [])

        if not mentions:
            mentions = self._extract_mentions_from_rich_content(validated_data.get("rich_content"))

        slug: str = validated_data.pop("slug", "")
        request = self.context["request"]

        mentions = self._filter_mentions_to_organization(mentions, self.context["get_organization"]().id)
        if not _mentions_allowed_for_comment_target(
            team_id=instance.team_id,
            scope=validated_data.get("scope", instance.scope),
            item_id=validated_data.get("item_id", instance.item_id),
            item_context=validated_data.get("item_context", instance.item_context),
        ):
            mentions = []

        with transaction.atomic():
            locked_instance = Comment.objects.select_for_update().get(pk=instance.pk)

            if locked_instance.created_by != request.user:
                raise exceptions.PermissionDenied("You can only modify your own comments")

            updated_instance = locked_instance
            if validated_data.keys():
                if validated_data.get("content"):
                    validated_data["version"] = locked_instance.version + 1

                updated_instance = super().update(locked_instance, validated_data)

        if mentions:
            if updated_instance.scope not in DESKTOP_COMMENT_SCOPES:
                send_discussions_mentioned.delay(updated_instance.id, mentions, slug)
            produce_discussion_mention_events(updated_instance, mentions, slug)
            send_mention_notifications(updated_instance, mentions, slug)
            _record_task_comment_activity(
                updated_instance,
                mentions,
                activity_at=timezone.now(),
                include_relationship_recipients=False,
            )

        return updated_instance


class CommentErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Human-readable explanation of what went wrong.")
    error_type = serializers.CharField(required=False, help_text="Stable machine-readable identifier for the failure.")


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
    task_id = serializers.UUIDField(
        required=False, help_text="Owning task for task, task_artifact, and desktop_canvas comment scopes."
    )
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
            "slack_channel_name",
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
            "slack_channel_name": {
                "help_text": "Slack channel name resolved from Slack at send time (no leading #). "
                "Empty for private channels and when unknown."
            },
            "slack_thread_ts": {"help_text": "Slack thread timestamp anchoring the mirrored thread."},
            "slack_team_id": {"help_text": "Slack workspace ID, used to route inbound replies back."},
        }


class SendCommentToSlackSerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(
        help_text="ID of the Slack integration (kind='slack') whose bot posts the thread."
    )
    channel_id = serializers.CharField(
        max_length=255,
        help_text="Slack channel ID to create the mirrored thread in. The bot must be a member of the channel. "
        "The channel's display name is resolved server-side.",
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
            candidate_scopes.add(_normalize_scope(query_scope))
        if pk := self.kwargs.get("pk"):
            try:
                candidate_scopes.add(
                    Comment.objects.filter(team_id=self.team_id, pk=pk).values_list("scope", flat=True).first()
                )
            except (ValueError, django_exceptions.ValidationError):
                return None
        if request.method not in ("GET", "HEAD", "OPTIONS") and isinstance(request.data, dict):
            if body_scope := request.data.get("scope"):
                candidate_scopes.add(_normalize_scope(body_scope))
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
                except (ValueError, django_exceptions.ValidationError):
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

    def _build_reply_fingerprint(self, validated_data: dict[str, Any]) -> "reply_dedupe.ReplyFingerprint | None":
        created_by = validated_data.get("created_by")
        source_comment = validated_data.get("source_comment")
        return reply_dedupe.ReplyFingerprint.build(
            team_id=self.team_id,
            created_by_id=getattr(created_by, "id", None),
            scope=validated_data.get("scope"),
            item_id=validated_data.get("item_id"),
            content=validated_data.get("content"),
            rich_content=validated_data.get("rich_content"),
            item_context=validated_data.get("item_context"),
            source_comment_id=getattr(source_comment, "id", None),
            is_task=validated_data.get("is_task"),
            has_unverifiable_metadata=bool(validated_data.get("mentions") or validated_data.get("slug")),
        )

    def _created_response(self, serializer: serializers.BaseSerializer[Any]) -> Response:
        data = serializer.data
        return Response(data, status=status.HTTP_201_CREATED, headers=self.get_success_headers(data))

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=CommentSerializer,
                description=(
                    "An identical support message was already created by a recent request. "
                    "The original comment is returned and nothing new is written."
                ),
            ),
            201: OpenApiResponse(response=CommentSerializer),
            409: OpenApiResponse(
                response=CommentErrorSerializer,
                description="An identical support message is still being created by another request.",
            ),
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Create a comment.

        Support messages are deduplicated: an identical message from the same author on the same
        ticket within a short window returns the original comment with a 200 instead of creating a
        second one, and a 409 while a concurrent request is still creating it.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Validate first, so the guard runs behind the ticket-editor check in the serializer rather
        # than reserving a key for a request that was never allowed to write.
        fingerprint = self._build_reply_fingerprint(serializer.validated_data)
        if fingerprint is None:
            self.perform_create(serializer)
            return self._created_response(serializer)

        def save_comment() -> Comment:
            self.perform_create(serializer)
            return cast(Comment, serializer.instance)

        guarded = reply_dedupe.create_deduplicated(fingerprint, save_comment)
        if guarded.outcome is reply_dedupe.CreateOutcome.CONFLICT:
            return Response(
                {
                    "detail": reply_dedupe.REPLY_IN_PROGRESS_DETAIL,
                    "error_type": reply_dedupe.REPLY_IN_PROGRESS_ERROR_TYPE,
                },
                status=status.HTTP_409_CONFLICT,
            )
        if guarded.outcome is reply_dedupe.CreateOutcome.REPLAYED:
            # Serialize the stored row directly. Going back through save() would re-fire the
            # mention notifications the original request already sent.
            return Response(self.get_serializer(guarded.comment).data)

        return self._created_response(serializer)

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

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context["get_user_access_control"] = lambda: self.user_access_control
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

    def _require_ticket_viewer_access_for_pk(self) -> None:
        """Gate a detail action on the ticket its target comment belongs to.

        Detail actions carry no scope param, so the queryset-level ticket filter never runs for
        them — and API scope access doesn't help a session caller denied the ticket. An item_id
        that resolves to no ticket is left alone: the write path rejects those, so only fixtures
        have them and there is no ticket content to protect.
        """
        from products.conversations.backend.models.ticket import (  # noqa: PLC0415 — keeps the generic comments API decoupled from the conversations product, only imported for ticket-scoped reads
            Ticket,
        )

        pk = self.kwargs.get("pk")
        if not pk:
            return
        try:
            target = Comment.objects.filter(team_id=self.team_id, pk=pk).values_list("scope", "item_id").first()
        except (ValueError, django_exceptions.ValidationError):
            return
        if not target:
            return
        scope, item_id = target
        if scope not in TICKET_COMMENT_SCOPES or not item_id:
            return
        try:
            ticket = Ticket.objects.get(team_id=self.team_id, id=item_id)
        except (Ticket.DoesNotExist, ValueError, django_exceptions.ValidationError):
            return
        if not self.user_access_control.check_access_level_for_object(ticket, required_level="viewer"):
            # Match the list path, where a denied ticket's comments are simply absent.
            raise exceptions.NotFound()

    def _require_task_comment_viewer_access_for_pk(self) -> None:
        pk = self.kwargs.get("pk")
        if not pk:
            return
        try:
            comment = Comment.objects.filter(team_id=self.team_id, pk=pk).first()
        except (ValueError, django_exceptions.ValidationError):
            return
        if comment is None or comment.scope not in {"task", "task_artifact", "desktop_canvas"}:
            return
        item_context = comment.item_context if isinstance(comment.item_context, dict) else {}
        task_id = comment.item_id if comment.scope == "task" else item_context.get("taskId")
        if not task_comment_target_is_accessible(
            team_id=self.team_id,
            user_id=self.request.user.id,
            task_id=task_id or "",
            scope=comment.scope,
            item_id=comment.item_id,
        ):
            raise exceptions.NotFound()

    def safely_get_object(self, queryset: QuerySet) -> Comment:
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_value = self.kwargs[lookup_url_kwarg]
        comment = get_object_or_404(queryset, **{self.lookup_field: lookup_value})
        if comment.scope in {"task", "task_artifact", "desktop_canvas"}:
            task_id = comment.item_id if comment.scope == "task" else (comment.item_context or {}).get("taskId")
            if not task_comment_target_is_accessible(
                team_id=self.team_id,
                user_id=self.request.user.id,
                task_id=task_id or "",
                scope=comment.scope,
                item_id=comment.item_id,
            ):
                raise exceptions.NotFound()
        return comment

    def _filter_ticket_scoped_queryset(self, queryset: QuerySet, item_id: str | None) -> QuerySet:
        """Ticket-carrying comments are ticket content — restrict them to tickets the caller has
        viewer access to, mirroring TicketViewSet's own object-level filtering."""
        from products.conversations.backend.models.ticket import (  # noqa: PLC0415 — keeps the generic comments API decoupled from the conversations product, only imported for ticket-scoped reads
            Ticket,
        )

        if item_id:
            try:
                ticket = Ticket.objects.get(team_id=self.team_id, id=item_id)
            except (Ticket.DoesNotExist, ValueError, django_exceptions.ValidationError):
                return queryset.none()
            if not self.user_access_control.check_access_level_for_object(ticket, required_level="viewer"):
                return queryset.none()
            return queryset

        # filter_queryset_by_access_level trusts the view to have enforced resource-level access
        # already, and this view is authorized as `comment` — so a caller denied the ticket resource
        # would otherwise get the unfiltered ticket queryset back here.
        if not self.user_access_control.check_access_level_for_resource(
            "ticket", "viewer"
        ) and not self.user_access_control.has_any_specific_access_for_resource("ticket", "viewer"):
            return queryset.none()

        visible_ticket_ids = self.user_access_control.filter_queryset_by_access_level(
            Ticket.objects.filter(team_id=self.team_id)
        ).values_list("id", flat=True)
        return queryset.filter(item_id__in=[str(ticket_id) for ticket_id in visible_ticket_ids])

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        params = self.request.GET.dict()
        queryset = queryset.exclude(scope__in=COMMENT_SCOPES_BLOCKED_FROM_GENERIC_API)

        if params.get("user"):
            queryset = queryset.filter(user=params.get("user"))

        if self.action != "partial_update" and params.get("deleted", "false") == "false":
            queryset = queryset.filter(deleted=False)

        scope = params.get("scope")
        if scope:
            queryset = queryset.filter(scope=scope)
            if scope in TICKET_COMMENT_SCOPES:
                queryset = self._filter_ticket_scoped_queryset(queryset, params.get("item_id"))
            elif scope in {"task", "task_artifact", "desktop_canvas"}:
                task_id = params.get("task_id")
                item_id = params.get("item_id")
                if not task_comment_target_is_accessible(
                    team_id=self.team_id,
                    user_id=self.request.user.id,
                    task_id=task_id or "",
                    scope=scope,
                    item_id=item_id,
                ):
                    return queryset.none()
                if scope != "task":
                    queryset = queryset.filter(item_context__taskId=str(task_id))
        elif self.action in ("list", "count"):
            # Product-owned scopes require their own object-level access checks and must
            # never leak through an unscoped generic comments query.
            queryset = queryset.exclude(scope__in=[*TICKET_COMMENT_SCOPES, "task", "task_artifact", "desktop_canvas"])
        else:
            self._require_ticket_viewer_access_for_pk()
            self._require_task_comment_viewer_access_for_pk()

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
        if comment.scope in TICKET_COMMENT_SCOPES:
            _require_ticket_editor_access(
                team_id=self.team_id, item_id=comment.item_id, user_access_control=self.user_access_control
            )
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
        if comment.scope in TICKET_COMMENT_SCOPES:
            _require_ticket_editor_access(
                team_id=self.team_id, item_id=comment.item_id, user_access_control=self.user_access_control
            )
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

    def _resolve_slack_channel_name(self, integration: Integration, channel_id: str, user: User) -> str:
        """Resolve the target channel server-side — the caller-supplied id is never paired with a
        caller-supplied label. Private channels are restricted to the workspace connector (matching
        the channel picker, which hides them from everyone else) and their names are never persisted,
        since the stored name is shown to every reader of the discussion.
        """
        client = SlackIntegration(integration).client
        client.timeout = 10  # keep a slow Slack workspace from pinning the request worker
        try:
            channel = client.conversations_info(channel=channel_id)["channel"]
        except SlackApiError as e:
            slack_error = (e.response.get("error") if e.response else None) or "unknown error"
            raise exceptions.ValidationError(f"Could not look up the Slack channel ({slack_error})")
        # A 1:1 DM reports is_im (not is_private), so it would sail past the private-channel
        # guard and let any member mirror a discussion into someone's DMs with the bot.
        if channel.get("is_im") or channel.get("is_mpim"):
            raise exceptions.ValidationError("Discussions can only be sent to Slack channels, not direct messages")
        if channel.get("is_private"):
            if integration.created_by_id != user.id:
                raise exceptions.PermissionDenied(
                    "Only the user who connected this Slack workspace can send a discussion to a private channel"
                )
            return ""
        return channel.get("name") or ""

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

        channel_name = self._resolve_slack_channel_name(integration, channel_id, cast(User, request.user))

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
                "slack_channel_name": channel_name,
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
            slack_thread.slack_channel_name = channel_name
            slack_thread.slack_team_id = integration.integration_id
            slack_thread.created_by = cast(User, request.user)
            slack_thread.created_at = timezone.now()
            slack_thread.save(
                update_fields=[
                    "integration",
                    "slack_channel_id",
                    "slack_channel_name",
                    "slack_team_id",
                    "created_by",
                    "created_at",
                ]
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
                organization_id=self.team.organization_id,
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
