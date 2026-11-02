import time
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from django.core.cache import cache
from django.db import transaction

import structlog
import posthoganalytics
from celery import Task, shared_task
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from posthog.comment.formatting import slack_files_to_placeholder_lines, slack_to_content_and_rich_content
from posthog.helpers.slack_thread_mirror import post_comment_to_slack_thread, slack_author_from_user
from posthog.integrations import IntegrationManager, IntegrationNotFound
from posthog.models.comment import Comment, CommentSlackThread
from posthog.models.comment.comment import COMMENT_SCOPES_BLOCKED_FROM_GENERIC_API, OBSERVATION_COMMENT_SCOPES
from posthog.models.comment.slack_thread import DISCUSSIONS_SLACK_SYNC_FLAG
from posthog.models.comment.utils import build_comment_item_url, comment_scope_display_name
from posthog.models.integration import SlackIntegration
from posthog.models.team import Team
from posthog.models.user import User
from posthog.scoping_audit import skip_team_scope_audit
from posthog.slack.channels import is_internal_channel, post_message, section_block
from posthog.slack.identity import resolve_posthog_user_for_slack, resolve_slack_user

from products.conversations.backend.facade.api import slack_thread_is_ticket_thread

logger = structlog.get_logger(__name__)

# item_context key holding the source Slack message ts of an ingested reply — the
# idempotency key that makes re-processing the same Slack event a no-op.
SLACK_MESSAGE_TS_KEY = "slack_message_ts"

# item_context key holding the Slack ts of a reply's mirrored copy. Its presence is the
# idempotency marker that keeps Celery retries and backfill re-runs from double-posting.
SLACK_SYNCED_TS_KEY = "slack_synced_ts"

# A discussion's reply history is caller-controlled and unbounded, and each post can block on a
# rate-limit wait, so one backfill run takes a bounded slice and reschedules the rest. Without
# this, mirroring a few large discussions could hold shared workers for a long time.
BACKFILL_BATCH_SIZE = 25
BACKFILL_SLEEP_BUDGET_SECONDS = 60
BACKFILL_RESCHEDULE_COUNTDOWN_SECONDS = 60


def _organization_id_for_team(team_id: int) -> str | None:
    return Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()


def _sync_killed(team_id: int) -> bool:
    """Kill switch for syncing on existing mirrors: only an explicit flag *off* halts it.

    The fail-closed creation gate is send_to_slack; here a flag-evaluation error or missing
    flag (None) must not silently drop user replies, so only False stops the sync. Evaluated
    with the same org/project groups as the request path, so a project-targeted disable also
    stops sync on mirrors that already exist.
    """
    try:
        team_ref = Team.objects.filter(id=team_id).values_list("uuid", "organization_id").first()
        if team_ref is None:
            return False
        team_uuid, organization_id = team_ref
        return (
            posthoganalytics.feature_enabled(
                DISCUSSIONS_SLACK_SYNC_FLAG,
                str(team_uuid),
                groups={"organization": str(organization_id), "project": str(team_id)},
            )
            is False
        )
    except Exception:
        return False


def _slack_retry_after(exc: Exception) -> int | None:
    """Seconds Slack asked us to wait when the failure is a rate limit; None for other errors."""
    if not isinstance(exc, SlackApiError) or exc.response is None:
        return None
    if exc.response.get("error") != "ratelimited":
        return None
    try:
        return min(int(exc.response.headers.get("Retry-After", "1")), 30)
    except (AttributeError, TypeError, ValueError):
        return 1


def _post_backfill_reply(
    client: WebClient, mirror: CommentSlackThread, reply: Comment, organization_id: str | None
) -> str | None:
    author_name, author_email = slack_author_from_user(reply.created_by)
    return post_comment_to_slack_thread(
        client=client,
        channel=mirror.slack_channel_id,
        content=reply.content or "",
        rich_content=reply.rich_content,
        author_name=author_name,
        author_email=author_email,
        workspace=mirror.slack_team_id,
        thread_ts=mirror.slack_thread_ts,
        organization_id=organization_id,
    )


def _log_backfill_reply_failure(comment_slack_thread_id: str, reply: Comment) -> None:
    logger.warning(
        "comment_slack_backfill_reply_failed",
        comment_slack_thread_id=comment_slack_thread_id,
        comment_id=str(reply.id),
    )


def _neutralize_rich_content_images(node: dict[str, Any] | list[Any] | object) -> None:
    """Escape markdown image syntax in every text node of an inbound reply's rich content."""
    if isinstance(node, dict):
        typed_node = cast(dict[str, Any], node)
        text = typed_node.get("text")
        if typed_node.get("type") == "text" and isinstance(text, str):
            typed_node["text"] = text.replace("![", "!\\[")
        for value in typed_node.values():
            _neutralize_rich_content_images(value)
    elif isinstance(node, list):
        for item in node:
            _neutralize_rich_content_images(item)


def _mark_reply_synced(reply: Comment, ts: object) -> None:
    item_context = dict(reply.item_context) if isinstance(reply.item_context, dict) else {}
    item_context[SLACK_SYNCED_TS_KEY] = ts if isinstance(ts, str) else ""
    Comment.objects.filter(id=reply.id).update(item_context=item_context)


def _reply_skip_reason(reply: Comment) -> str | None:
    if reply.scope in COMMENT_SCOPES_BLOCKED_FROM_GENERIC_API or reply.scope in OBSERVATION_COMMENT_SCOPES:
        return "protected_scope"
    item_context = reply.item_context if isinstance(reply.item_context, dict) else {}
    if item_context.get("from_slack"):
        return "from_slack"  # came in from Slack — echoing it back would loop
    if item_context.get("is_emoji"):
        return "emoji"  # reactions are stored as reply comments but aren't messages
    if SLACK_SYNCED_TS_KEY in item_context:
        return "already_synced"
    return None


def slack_message_comment_content(text: str, blocks: list | None, files: list | None) -> tuple[str, Any] | None:
    """A Slack message as discussion-comment ``(content, rich_content)``, or None when it has nothing to show.

    Shared by the live reply ingest, the opening comment of a linked thread and the import of its
    history, so a message reads the same whichever path brought it in.
    """
    content, rich_content = slack_to_content_and_rich_content(text, blocks)
    file_placeholders = slack_files_to_placeholder_lines(files)
    if not content and not rich_content and not file_placeholders:
        return None
    # Slack text has no markdown image syntax, so neutralizing it is lossless — and keeps an
    # external participant's reply from making the discussion UI load remote images. The UI
    # prefers rich_content (flattened back to markdown), so its text nodes need the same
    # treatment or the escape would be sidestepped whenever the message carries blocks.
    content = content.replace("![", "!\\[")
    _neutralize_rich_content_images(rich_content)

    if file_placeholders:
        # Appended after the image neutralization above, which would otherwise escape the very
        # markdown links being added. Their filenames are escaped at construction instead.
        placeholder_text = "\n\n".join(file_placeholders)
        content = f"{content}\n\n{placeholder_text}" if content else placeholder_text
        # The UI prefers rich_content whenever it's set, so placeholders added only to content
        # would be invisible for any upload that arrived with a caption (and so with blocks).
        if isinstance(rich_content, dict):
            nodes = rich_content.get("content")
            if not isinstance(nodes, list):
                nodes = []
                rich_content["content"] = nodes
            nodes.extend(
                {"type": "paragraph", "content": [{"type": "text", "text": line}]} for line in file_placeholders
            )
    return content, rich_content


def slack_author_fields(user_info: dict, *, workspace_id: str | None, team: Team) -> tuple[User | None, dict[str, Any]]:
    """Who a Slack-authored comment is by: the PostHog user to credit, and its item_context stamp.

    Only attributes the comment to a PostHog user when Slack confirms the author belongs to the
    integration's own workspace (``workspace_id``). In externally-shared (Slack Connect) channels the other
    workspace's admin controls its users' profile emails, so trusting the email there would let
    an outsider post as any org member.
    """
    posthog_user = None
    if user_info.get("team_id") and user_info.get("team_id") == workspace_id:
        posthog_user = resolve_posthog_user_for_slack(user_info.get("email"), team)
    # Slack users without a verified PostHog account stay author-less; their display identity
    # rides in item_context (name + avatar only — no email or Slack user id, which would leak
    # external participants' PII through the comments API).
    return posthog_user, {
        "from_slack": True,
        "slack_author_name": user_info["name"],
        "slack_author_avatar": user_info.get("avatar"),
    }


def slack_profile_unresolved(user_info: dict) -> bool:
    """Whether resolve_slack_user fell back to its "Unknown" profile because users.info didn't answer.

    A real Slack user always comes back with the workspace it belongs to.
    """
    return user_info.get("team_id") is None and user_info.get("name") == "Unknown" and not user_info.get("email")


def slack_ts_to_datetime(ts: str) -> datetime | None:
    # A Slack ts is the post time in epoch seconds, with microseconds after the dot.
    try:
        return datetime.fromtimestamp(float(ts), tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def fetch_slack_thread_page(
    client: WebClient, *, channel: str, thread_ts: str, limit: int, cursor: str | None = None
) -> tuple[list[dict[str, Any]], str | None]:
    """One page of a Slack thread's messages, oldest first, and the cursor for the next page or None.

    Slack's errors propagate.
    """
    response = client.conversations_replies(channel=channel, ts=thread_ts, limit=limit, cursor=cursor)
    messages = [m for m in response.get("messages") or [] if isinstance(m, dict)]
    next_cursor = (response.get("response_metadata") or {}).get("next_cursor") if response.get("has_more") else None
    return messages, next_cursor or None


def _slack_reply_exists(team_id: int, mirror: CommentSlackThread, message_ts: str) -> bool:
    return Comment.objects.filter(
        team_id=team_id,
        source_comment_id=mirror.source_comment_id,
        item_context__slack_message_ts=message_ts,
    ).exists()


def _save_slack_reply_once(
    mirror: CommentSlackThread,
    team: Team,
    *,
    content: str,
    rich_content: Any,
    posthog_user: User | None,
    author_context: dict[str, Any],
    message_ts: str,
    created_at: datetime | None = None,
) -> Comment | None:
    """Save a Slack message as a reply on the mirrored discussion, unless it is already there.

    Returns None when the message was already saved. The live ingest and a linked thread's history
    import can reach the same message at the same moment, and the comment table has no unique key
    on the Slack ts. Locking the mirror row makes the check and the insert one step per thread, so
    the second path finds the first path's comment.
    """
    with transaction.atomic():
        list(CommentSlackThread.objects.unscoped().select_for_update().filter(id=mirror.id).values_list("id"))
        if _slack_reply_exists(team.id, mirror, message_ts):
            return None
        comment = Comment.objects.create(
            team=team,
            scope=mirror.scope,
            item_id=mirror.item_id,
            # The reply hangs off the mirrored thread's root comment (None only for whole-item mirrors).
            source_comment_id=mirror.source_comment_id,
            content=content,
            rich_content=rich_content,
            created_by=posthog_user,
            item_context={**author_context, SLACK_MESSAGE_TS_KEY: message_ts},
        )
        if created_at is not None:
            # created_at is auto_now_add, so imported history takes its Slack time in a second write.
            Comment.objects.filter(id=comment.id).update(created_at=created_at)
            comment.created_at = created_at
    return comment


# How long a linked channel's "internal" verdict is trusted before Slack is asked again. Short, because
# a channel that turns into a Slack Connect channel must stop receiving internal replies soon after.
LINKED_CHANNEL_CHECK_CACHE_SECONDS = 600


def _is_linked_root(root_id: UUID | str) -> bool:
    """Whether a discussion was linked from an existing Slack thread, rather than sent to Slack.

    Only a linked discussion's opening comment came from Slack.
    """
    context = Comment.objects.filter(id=root_id).values_list("item_context", flat=True).first()
    return isinstance(context, dict) and context.get("from_slack") is True


def _linked_thread_post_refusal(
    mirror: CommentSlackThread, slack: SlackIntegration, organization_id: str | None
) -> str | None:
    """Why a linked thread must stop receiving discussion replies, or None when it may receive them.

    Linking checks both rules once, and either can stop holding later: someone can share the
    channel with another workspace, or a customer can open a support ticket in the thread. The
    next internal reply would then reach people outside the team, and a post can't be taken back.
    A Slack error propagates so the caller retries rather than posting unchecked.
    """
    if organization_id and slack_thread_is_ticket_thread(
        organization_id=organization_id,
        slack_channel_id=mirror.slack_channel_id,
        slack_thread_ts=mirror.slack_thread_ts,
    ):
        return "support_ticket"
    cache_key = f"comment_slack_thread:internal_channel:{mirror.slack_team_id}:{mirror.slack_channel_id}"
    internal = cache.get(cache_key)
    if internal is None:
        channel = slack.client.conversations_info(channel=mirror.slack_channel_id)["channel"]
        internal = is_internal_channel(channel)
        cache.set(cache_key, internal, LINKED_CHANNEL_CHECK_CACHE_SECONDS)
    return None if internal else "channel_not_internal"


# Retry budget must outlast a slow root post in send_to_slack (up to two 10s Slack calls),
# or a reply created mid-send would exhaust retries and never reach the thread.
@shared_task(bind=True, ignore_result=True, max_retries=6, default_retry_delay=10)
@skip_team_scope_audit  # Comment is on RootTeamManager; queries pin the team via the comment/mirror rows
def mirror_comment_reply_to_slack(self: Task, comment_id: str) -> None:
    """Post a newly-created discussion reply into its parent's mirrored Slack thread.

    A discussion mirrors to exactly one Slack thread (1:1). Retries on a Slack failure rather
    than silently dropping the reply, and stamps the posted ts onto the reply so a retry after
    a successful post (e.g. worker death between the Slack ack and the task ack) can't re-post.
    """
    comment = Comment.objects.filter(id=comment_id).select_related("created_by").first()
    if comment is None or not comment.source_comment_id or _reply_skip_reason(comment):
        return
    if _sync_killed(comment.team_id):
        return

    mirror = (
        CommentSlackThread.objects.for_team(comment.team_id)
        .filter(source_comment_id=comment.source_comment_id)
        .select_related("integration")
        .first()
    )
    if mirror is None:
        return
    if not mirror.slack_thread_ts:
        # Reserved but the root post hasn't landed yet (send_to_slack mid-flight) — retry rather
        # than dropping the reply. A failed root post deletes the reservation, so the retry then
        # exits on mirror is None.
        raise self.retry()

    author_name, author_email = slack_author_from_user(comment.created_by)
    organization_id = _organization_id_for_team(comment.team_id)
    try:
        slack = SlackIntegration(mirror.integration)
        if _is_linked_root(comment.source_comment_id):
            refusal = _linked_thread_post_refusal(mirror, slack, organization_id)
            if refusal is not None:
                logger.warning(
                    "linked_slack_thread_post_refused",
                    comment_slack_thread_id=str(mirror.id),
                    team_id=comment.team_id,
                    reason=refusal,
                )
                return
        client = slack.client
        posted_ts = post_comment_to_slack_thread(
            client=client,
            channel=mirror.slack_channel_id,
            content=comment.content or "",
            rich_content=comment.rich_content,
            author_name=author_name,
            author_email=author_email,
            workspace=mirror.slack_team_id,
            thread_ts=mirror.slack_thread_ts,
            organization_id=organization_id,
        )
    except Exception as exc:
        raise self.retry(exc=exc)
    _mark_reply_synced(comment, posted_ts)


@shared_task(bind=True, ignore_result=True, max_retries=3, default_retry_delay=5)
@skip_team_scope_audit  # Comment is on RootTeamManager; queries pin the team via the mirror's integration
def ingest_slack_discussion_reply(
    self: Task,
    comment_slack_thread_id: str,
    slack_user_id: str,
    text: str,
    blocks: list | None,
    message_ts: str,
    # Defaulted so replies enqueued under the previous signature still run during a deploy.
    files: list | None = None,
) -> None:
    """Save a Slack thread reply as a discussion comment (the inbound mirror half).

    Runs off the webhook request thread: Slack expects the events endpoint to ack in ~3
    seconds and this path makes a ``users.info`` call. Idempotent per source Slack message
    ts, so task retries and duplicate event deliveries can't create duplicate comments.
    """
    mirror = (
        CommentSlackThread.objects.unscoped()
        .filter(id=comment_slack_thread_id)
        .select_related("integration__team")
        .first()
    )
    if mirror is None or mirror.scope in OBSERVATION_COMMENT_SCOPES:
        return
    # message_ts is the idempotency key; without it a redelivered event would duplicate the
    # comment (the enqueuing side already refuses these — this is the fail-closed backstop).
    if not message_ts:
        return
    team = mirror.integration.team
    if _sync_killed(team.id):
        return

    if _slack_reply_exists(team.id, mirror, message_ts):
        return

    converted = slack_message_comment_content(text, blocks, files)
    if converted is None:
        return
    content, rich_content = converted

    try:
        client = SlackIntegration(mirror.integration).client
        client.timeout = 10
        # The profile feeds the workspace-membership trust check in slack_author_fields — namespace
        # the cache by this integration's workspace so a colliding user id from another workspace
        # (Slack Connect) can't be served from a stale entry.
        user_info = resolve_slack_user(client, slack_user_id, workspace=mirror.integration.integration_id or "")
    except Exception as exc:
        raise self.retry(exc=exc)

    posthog_user, author_context = slack_author_fields(
        user_info, workspace_id=mirror.integration.integration_id, team=team
    )
    saved = _save_slack_reply_once(
        mirror,
        team,
        content=content,
        rich_content=rich_content,
        posthog_user=posthog_user,
        author_context=author_context,
        message_ts=message_ts,
    )
    if saved is None:
        return
    logger.info(
        "slack_discussion_reply_ingested",
        team_id=team.id,
        scope=mirror.scope,
        item_id=mirror.item_id,
        comment_slack_thread_id=comment_slack_thread_id,
    )


@shared_task(ignore_result=True)
@skip_team_scope_audit  # Comment is on RootTeamManager; the reply query filters by the mirror's team_id
def backfill_comment_slack_thread(comment_slack_thread_id: str) -> None:
    """Post a discussion's pre-existing replies into a freshly-mirrored Slack thread.

    Runs asynchronously after send_to_slack — so the request isn't blocked on N sequential Slack
    posts. Bounded to replies created before the mirror: later replies belong exclusively to the
    live post_save signal, so the two paths can't both post the same reply. Best-effort per reply —
    a failure on one is logged and skipped — and each success is stamped with its posted ts, so a
    re-run never double-posts.

    Each run takes at most BACKFILL_BATCH_SIZE replies and spends at most
    BACKFILL_SLEEP_BUDGET_SECONDS waiting out rate limits, then reschedules itself for the rest.
    That keeps one big discussion from occupying a shared worker for an unbounded stretch.
    """
    mirror = (
        CommentSlackThread.objects.unscoped().filter(id=comment_slack_thread_id).select_related("integration").first()
    )
    if mirror is None or not mirror.source_comment_id or not mirror.slack_thread_ts:
        return
    if _sync_killed(mirror.team_id):
        return

    try:
        client = SlackIntegration(mirror.integration).client
    except Exception:
        logger.warning("comment_slack_backfill_client_failed", comment_slack_thread_id=comment_slack_thread_id)
        return

    organization_id = _organization_id_for_team(mirror.team_id)

    # source_comment_id matches the thread root, so this returns its replies (not the root itself).
    # Already-stamped replies are excluded in SQL rather than skipped in Python, so each run's
    # batch is fresh work and a rescheduled run makes progress instead of re-walking the tail.
    replies = (
        Comment.objects.filter(
            team_id=mirror.team_id,
            source_comment_id=mirror.source_comment_id,
            deleted=False,
            created_at__lt=mirror.created_at,
        )
        .exclude(item_context__has_key=SLACK_SYNCED_TS_KEY)
        .select_related("created_by")
        .order_by("created_at")
    )
    batch = list(replies[: BACKFILL_BATCH_SIZE + 1])
    remaining = len(batch) > BACKFILL_BATCH_SIZE
    slept_seconds = 0
    synced_any = False
    for reply in batch[:BACKFILL_BATCH_SIZE]:
        if slept_seconds >= BACKFILL_SLEEP_BUDGET_SECONDS:
            remaining = True
            break
        if _reply_skip_reason(reply):
            continue
        try:
            posted_ts = _post_backfill_reply(client, mirror, reply, organization_id)
        except Exception as exc:
            # chat.postMessage allows ~1 msg/sec per channel, so a long backfill will get rate
            # limited; honoring Retry-After once keeps the whole thread mirroring instead of
            # silently dropping its tail.
            retry_after = _slack_retry_after(exc)
            if retry_after is None:
                _log_backfill_reply_failure(comment_slack_thread_id, reply)
                continue
            time.sleep(retry_after)
            slept_seconds += retry_after
            try:
                posted_ts = _post_backfill_reply(client, mirror, reply, organization_id)
            except Exception:
                _log_backfill_reply_failure(comment_slack_thread_id, reply)
                continue
        _mark_reply_synced(reply, posted_ts)
        synced_any = True

    # Only continue while the run is actually draining the queue. A batch where every post failed
    # leaves the same rows unstamped, so rescheduling on `remaining` alone would loop forever.
    if remaining and synced_any:
        backfill_comment_slack_thread.apply_async(
            (comment_slack_thread_id,), countdown=BACKFILL_RESCHEDULE_COUNTDOWN_SECONDS
        )


# A linked thread's history is imported one page per task run, so a long thread never holds a worker
# for long and a failure retries only the page it hit. The cap bounds what one link can pull in;
# past it the root's import state says the history was cut short.
LINKED_THREAD_IMPORT_PAGE_SIZE = 200
LINKED_THREAD_IMPORT_MESSAGE_LIMIT = 1000
LINKED_THREAD_IMPORT_SOURCE = "discussion_slack_import"

# Stamped by the server on a linked thread's root comment. The import state tells API readers whether
# the thread's history is complete ("pending", "done", "truncated" or "failed"). The notice ts keeps
# the "now linked" notice to one post per link across task retries.
SLACK_IMPORT_STATE_KEY = "slack_import_state"
SLACK_LINK_NOTICE_TS_KEY = "slack_link_notice_ts"


class UnresolvedSlackAuthor(Exception):
    """users.info didn't answer for a message's author. Saving the message now would credit it to
    "Unknown" for good, because the save is keyed on the Slack ts and never revisited."""


def _history_message_skip_reason(message: dict[str, Any]) -> str | None:
    """Why a message already in a linked thread shouldn't become a discussion reply, else None.

    Matches the live gate in products/slack_app (``_thread_message_ignore_reason``) so the
    history reads like the replies that sync after it: app- and bot-authored posts are left out
    (PostHog's own mirror posts and the link notice among them), and so is system noise like
    channel joins. Two deliberate differences, both because this is a finished message rather
    than an event: an edited message is kept at its latest text, and an "also send to channel"
    reply is kept, since in a support side thread it is a person answering, not an announcement.
    """
    if not message.get("user") or message.get("user") == "USLACKBOT":
        return "no_user"
    if message.get("bot_id") or message.get("bot_profile") or message.get("app_id"):
        return "app_authored"
    subtype = message.get("subtype")
    if subtype not in (None, "file_share", "thread_broadcast"):
        return f"subtype:{subtype}"
    return None


def _stamp_root(mirror: CommentSlackThread, values: dict[str, str]) -> None:
    root = Comment.objects.filter(id=mirror.source_comment_id).only("item_context").first()
    if root is None:
        return
    context = dict(root.item_context) if isinstance(root.item_context, dict) else {}
    Comment.objects.filter(id=root.id).update(item_context={**context, **values})


def _post_link_notice(slack: SlackIntegration, mirror: CommentSlackThread) -> None:
    """Tell the thread it is now linked, once per link.

    Linking reads a conversation that people started without PostHog in mind, so they are told
    where their replies now show up. Best effort: a notice that fails to post doesn't hold back
    the import.
    """
    context = Comment.objects.filter(id=mirror.source_comment_id).values_list("item_context", flat=True).first()
    if isinstance(context, dict) and context.get(SLACK_LINK_NOTICE_TS_KEY):
        return
    url = build_comment_item_url(mirror.scope, mirror.item_id)
    text = (
        f"This thread is now linked to <{url}|{comment_scope_display_name(mirror.scope)}> in PostHog. "
        "Replies here show up there, and replies there are posted here."
    )
    try:
        response = post_message(
            slack, mirror.slack_channel_id, blocks=[section_block(text)], text=text, thread_ts=mirror.slack_thread_ts
        )
    except Exception:
        logger.warning("linked_slack_thread_notice_failed", comment_slack_thread_id=str(mirror.id), exc_info=True)
        return
    _stamp_root(mirror, {SLACK_LINK_NOTICE_TS_KEY: str(response.get("ts") or "posted")})


def _import_history_page(
    mirror: CommentSlackThread,
    team: Team,
    client: WebClient,
    messages: list[dict[str, Any]],
    *,
    workspace_id: str,
    allow_unresolved: bool,
) -> int:
    """Save one page of a linked thread's earlier replies. Returns how many were new."""
    # One read for the page instead of an exists() per message; the locked save still guards the
    # race with the live ingest.
    already_saved = set(
        Comment.objects.filter(team_id=team.id, source_comment_id=mirror.source_comment_id).values_list(
            "item_context__slack_message_ts", flat=True
        )
    )
    authors: dict[str, tuple[User | None, dict[str, Any]]] = {}
    imported = 0
    for message in messages:
        message_ts = str(message.get("ts") or "")
        # The root is already the discussion's opening comment.
        if not message_ts or message_ts == mirror.slack_thread_ts or message_ts in already_saved:
            continue
        if _history_message_skip_reason(message):
            continue
        converted = slack_message_comment_content(
            str(message.get("text") or ""),
            message.get("blocks") if isinstance(message.get("blocks"), list) else None,
            message.get("files") if isinstance(message.get("files"), list) else None,
        )
        if converted is None:
            continue
        content, rich_content = converted
        slack_user_id = str(message["user"])
        if slack_user_id not in authors:
            user_info = resolve_slack_user(client, slack_user_id, workspace=workspace_id)
            if slack_profile_unresolved(user_info) and not allow_unresolved:
                raise UnresolvedSlackAuthor(slack_user_id)
            authors[slack_user_id] = slack_author_fields(user_info, workspace_id=workspace_id, team=team)
        posthog_user, author_context = authors[slack_user_id]
        saved = _save_slack_reply_once(
            mirror,
            team,
            content=content,
            rich_content=rich_content,
            posthog_user=posthog_user,
            author_context=author_context,
            message_ts=message_ts,
            created_at=slack_ts_to_datetime(message_ts),
        )
        if saved is not None:
            imported += 1
    return imported


@shared_task(bind=True, ignore_result=True, max_retries=5, default_retry_delay=30)
@skip_team_scope_audit  # Comment is on RootTeamManager; writes pin the team via the mirror row
def import_linked_slack_thread(
    self: Task, comment_slack_thread_id: str, cursor: str | None = None, seen: int = 0
) -> None:
    """Bring the replies an existing Slack thread already had into the discussion it was linked to.

    The link action (CommentViewSet.link_slack_thread) creates the opening comment from the
    thread's root. This posts the "now linked" notice and then fills in what was said under the
    root, one page per run, each reply at its Slack time so the discussion reads in order. A
    reply posted in Slack while this runs can reach the live ingest as well. Both paths save
    through _save_slack_reply_once, so each Slack message becomes one comment and a retry is safe.

    A rate limit retries after Slack's Retry-After. When an author can't be resolved, the page
    is retried rather than saved under "Unknown", except on the last attempt. When retries run
    out, the root's import state says "failed".
    """
    mirror = CommentSlackThread.objects.unscoped().filter(id=comment_slack_thread_id).first()
    if mirror is None or not mirror.source_comment_id or not mirror.slack_thread_ts:
        return
    # Stopping here without a final state would leave the root saying its history is on its way.
    if _sync_killed(mirror.team_id):
        _stamp_root(mirror, {SLACK_IMPORT_STATE_KEY: "failed"})
        return
    try:
        integration = IntegrationManager.slack.oauth.get(mirror.team_id, mirror.integration_id)
    except IntegrationNotFound:
        _stamp_root(mirror, {SLACK_IMPORT_STATE_KEY: "failed"})
        return
    team = Team.objects.get(id=mirror.team_id)
    slack = SlackIntegration(integration, source=LINKED_THREAD_IMPORT_SOURCE)
    final_attempt = self.request.retries >= self.max_retries

    try:
        if cursor is None:
            _post_link_notice(slack, mirror)
        client = slack.client
        client.timeout = 10
        messages, next_cursor = fetch_slack_thread_page(
            client,
            channel=mirror.slack_channel_id,
            thread_ts=mirror.slack_thread_ts,
            limit=LINKED_THREAD_IMPORT_PAGE_SIZE,
            cursor=cursor,
        )
        imported = _import_history_page(
            mirror,
            team,
            client,
            messages,
            workspace_id=integration.integration_id or "",
            allow_unresolved=final_attempt,
        )
    except Exception as exc:
        if final_attempt:
            _stamp_root(mirror, {SLACK_IMPORT_STATE_KEY: "failed"})
            logger.warning(
                "linked_slack_thread_import_failed",
                comment_slack_thread_id=comment_slack_thread_id,
                error=type(exc).__name__,
            )
            return
        raise self.retry(exc=exc, countdown=_slack_retry_after(exc))

    seen += len(messages)
    if next_cursor and seen < LINKED_THREAD_IMPORT_MESSAGE_LIMIT:
        # A fresh task per page gets a fresh retry budget, so one bad page can't use up the thread's.
        import_linked_slack_thread.apply_async(
            kwargs={"comment_slack_thread_id": comment_slack_thread_id, "cursor": next_cursor, "seen": seen}
        )
    else:
        state = "truncated" if next_cursor else "done"
        _stamp_root(mirror, {SLACK_IMPORT_STATE_KEY: state})
        log = logger.warning if state == "truncated" else logger.info
        log("linked_slack_thread_imported", comment_slack_thread_id=comment_slack_thread_id, seen=seen, state=state)
    logger.info("linked_slack_thread_page_imported", comment_slack_thread_id=comment_slack_thread_id, imported=imported)
