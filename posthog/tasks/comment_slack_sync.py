import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from django.db.models import Q

import structlog
import posthoganalytics
from celery import Task, shared_task
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from posthog.comment.formatting import slack_files_to_placeholder_lines, slack_to_content_and_rich_content
from posthog.helpers.slack_identity import resolve_posthog_user_for_slack, resolve_slack_user
from posthog.helpers.slack_thread_mirror import post_comment_to_slack_thread, slack_author_from_user
from posthog.models.comment import SLACK_IMPORT_TERMINAL_STATUSES, Comment, CommentSlackThread, SlackImportStatus
from posthog.models.comment.slack_thread import DISCUSSIONS_SLACK_SYNC_FLAG
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.team import Team
from posthog.models.user import User
from posthog.scoping_audit import skip_team_scope_audit

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

# Ceiling on how much of a Slack thread one import pulls in. Bounded by the discussion UI rather
# than by Slack: the comments list loads a single 100-comment page and doesn't follow `next`, so a
# larger import would render an arbitrary window of itself. Raise this once that's paginated.
SLACK_IMPORT_MAX_MESSAGES = 200
# conversations.replies caps out at 1000 per page; 100 keeps a single page's write batch small.
SLACK_IMPORT_PAGE_SIZE = 100
SLACK_IMPORT_SLEEP_BUDGET_SECONDS = 30
# Short, unlike the outbound backfill's: Slack pagination cursors expire, so a rescheduled run
# needs to pick the walk back up promptly.
SLACK_IMPORT_RESCHEDULE_COUNTDOWN_SECONDS = 15

# Slack subtypes that still carry a person's typed message. Anything else — channel_join,
# channel_topic, tombstones, huddle threads — is system noise that would read as spam in a
# discussion. A plain message has no subtype at all.
IMPORTABLE_SLACK_SUBTYPES = frozenset({"thread_broadcast", "me_message", "file_share"})


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


def slack_ts_to_datetime(ts: str) -> datetime | None:
    """Slack's `"1712345678.000100"` as a UTC datetime, or None if it isn't a timestamp."""
    try:
        return datetime.fromtimestamp(float(ts), tz=UTC)
    except (TypeError, ValueError):
        return None


def _slack_message_body(
    text: str, blocks: list | None, files: list | None, user_names: dict[str, str] | None = None
) -> tuple[str, Any]:
    """Markdown + rich content for one Slack message, or ("", None) when there's nothing to show."""
    content, rich_content = slack_to_content_and_rich_content(text, blocks, user_names)
    file_placeholders = slack_files_to_placeholder_lines(files)
    if not content and not rich_content and not file_placeholders:
        return "", None
    # Slack text has no markdown image syntax, so neutralizing it is lossless — and keeps an
    # external participant's message from making the discussion UI load remote images. The UI
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


@dataclass(frozen=True)
class SlackCommentFields:
    """Everything needed to write one Slack message into the discussion as a Comment."""

    content: str
    rich_content: Any
    created_by: User | None
    item_context: dict[str, Any]


def slack_message_to_comment_fields(
    *,
    client: WebClient,
    integration: Integration,
    team: Team,
    message_ts: str,
    slack_user_id: str,
    text: str,
    blocks: list | None = None,
    files: list | None = None,
    user_names: dict[str, str] | None = None,
    user_info: dict | None = None,
) -> SlackCommentFields | None:
    """Convert a Slack message into Comment fields, or None when it carries nothing importable.

    Shared by the inbound webhook, the thread import's root, and the import's reply backfill, so
    all three agree on content conversion, author attribution and the item_context contract.
    Raises whatever the Slack profile lookup raises — callers decide whether to retry.
    """
    content, rich_content = _slack_message_body(text, blocks, files, user_names)
    if not content and not rich_content:
        return None

    if user_info is None:
        # The profile feeds the workspace-membership trust check below — namespace the cache by
        # this integration's workspace so a colliding user id from another workspace (Slack
        # Connect) can't be served from a stale entry.
        user_info = resolve_slack_user(client, slack_user_id, workspace=integration.integration_id or "")

    # Only attribute the comment to a PostHog user when Slack confirms the author belongs to
    # this integration's own workspace. In externally-shared (Slack Connect) channels the other
    # workspace's admin controls its users' profile emails, so trusting the email there would
    # let an outsider post as any org member.
    posthog_user = None
    if user_info.get("team_id") and user_info.get("team_id") == integration.integration_id:
        posthog_user = resolve_posthog_user_for_slack(user_info.get("email"), team)

    return SlackCommentFields(
        content=content,
        rich_content=rich_content,
        # Slack users without a verified PostHog account stay author-less; their display
        # identity rides in item_context (name + avatar only — no email or Slack user id,
        # which would leak external participants' PII through the comments API).
        created_by=posthog_user,
        item_context={
            "from_slack": True,
            SLACK_MESSAGE_TS_KEY: message_ts,
            "slack_author_name": user_info["name"],
            "slack_author_avatar": user_info.get("avatar"),
        },
    )


def build_slack_comment(
    *,
    team: Team,
    scope: str,
    item_id: str | None,
    # None for a thread root; a mirror's source_comment_id is a UUID.
    source_comment_id: str | UUID | None,
    fields: SlackCommentFields,
) -> Comment:
    """An unsaved Comment for a Slack message. Callers save it, or bulk_create a page of them."""
    return Comment(
        team=team,
        scope=scope,
        item_id=item_id,
        source_comment_id=source_comment_id,
        content=fields.content,
        rich_content=fields.rich_content,
        created_by=fields.created_by,
        item_context=fields.item_context,
    )


def _apply_slack_timestamps(comments: list[Comment], created_ats: list[datetime | None]) -> None:
    """Rewrite created_at to the original Slack times, so an imported thread reads in true order.

    Needed as a second write because created_at is auto_now_add, which stamps "now" in
    bulk_create just as it does in save(). bulk_update skips pre_save, so it sticks.
    """
    dated = [(comment, created_at) for comment, created_at in zip(comments, created_ats) if created_at is not None]
    if not dated:
        return
    for comment, created_at in dated:
        comment.created_at = created_at
    Comment.objects.bulk_update([comment for comment, _ in dated], ["created_at"])


def slack_import_skip_reason(message: dict) -> str | None:
    """Why this Slack thread message shouldn't become a discussion comment, or None to import it.

    Bot-authored messages are excluded partly because discussions have no way to render a bot
    author, and partly because that's what stops an import of a thread PostHog itself mirrors
    from re-importing our own posts — they always carry bot_id and never a user.
    """
    if message.get("bot_id") or message.get("bot_profile") or message.get("subtype") == "bot_message":
        return "bot_author"
    if message.get("app_id"):
        return "app_authored"
    user = message.get("user")
    if not user or user == "USLACKBOT":
        return "no_user"
    subtype = message.get("subtype")
    if subtype and subtype not in IMPORTABLE_SLACK_SUBTYPES:
        return f"subtype:{subtype}"
    return None


def _slack_message_already_ingested(mirror: CommentSlackThread, team_id: int, message_ts: str) -> bool:
    """Whether this Slack message is already in the discussion, anywhere in the mirrored thread.

    Spans the thread root as well as its replies. An imported thread's root *is* a Slack message,
    so matching only replies would let an edit to the Slack parent land as a reply duplicating
    the root.
    """
    return (
        Comment.objects.filter(team_id=team_id, item_context__slack_message_ts=message_ts)
        .filter(Q(id=mirror.source_comment_id) | Q(source_comment_id=mirror.source_comment_id))
        .exists()
    )


def _reply_skip_reason(reply: Comment) -> str | None:
    item_context = reply.item_context if isinstance(reply.item_context, dict) else {}
    if item_context.get("from_slack"):
        return "from_slack"  # came in from Slack — echoing it back would loop
    if item_context.get("is_emoji"):
        return "emoji"  # reactions are stored as reply comments but aren't messages
    if SLACK_SYNCED_TS_KEY in item_context:
        return "already_synced"
    return None


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
    try:
        client = SlackIntegration(mirror.integration).client
        posted_ts = post_comment_to_slack_thread(
            client=client,
            channel=mirror.slack_channel_id,
            content=comment.content or "",
            rich_content=comment.rich_content,
            author_name=author_name,
            author_email=author_email,
            thread_ts=mirror.slack_thread_ts,
            organization_id=_organization_id_for_team(comment.team_id),
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
    if mirror is None:
        return
    # message_ts is the idempotency key; without it a redelivered event would duplicate the
    # comment (the enqueuing side already refuses these — this is the fail-closed backstop).
    if not message_ts:
        return
    team = mirror.integration.team
    if _sync_killed(team.id):
        return

    if _slack_message_already_ingested(mirror, team.id, message_ts):
        return

    try:
        client = SlackIntegration(mirror.integration).client
        client.timeout = 10
        fields = slack_message_to_comment_fields(
            client=client,
            integration=mirror.integration,
            team=team,
            message_ts=message_ts,
            slack_user_id=slack_user_id,
            text=text,
            blocks=blocks,
            files=files,
        )
    except Exception as exc:
        raise self.retry(exc=exc)

    if fields is None:
        return

    build_slack_comment(
        team=team,
        scope=mirror.scope,
        item_id=mirror.item_id,
        # The reply hangs off the mirrored thread's root comment (None only for whole-item mirrors).
        source_comment_id=mirror.source_comment_id,
        fields=fields,
    ).save()
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


def _set_import_state(mirror: CommentSlackThread, **fields: Any) -> None:
    """Write import progress with .update() so a concurrent count write isn't clobbered."""
    CommentSlackThread.objects.unscoped().filter(id=mirror.id).update(**fields)


def _fetch_slack_thread_page(
    client: WebClient, mirror: CommentSlackThread, cursor: str | None
) -> tuple[list[dict], str | None]:
    """One page of the mirrored Slack thread, retried once if Slack asks us to slow down."""
    try:
        response = client.conversations_replies(
            channel=mirror.slack_channel_id,
            ts=mirror.slack_thread_ts,
            limit=SLACK_IMPORT_PAGE_SIZE,
            cursor=cursor or None,
        )
    except Exception as exc:
        retry_after = _slack_retry_after(exc)
        if retry_after is None or retry_after > SLACK_IMPORT_SLEEP_BUDGET_SECONDS:
            raise
        time.sleep(retry_after)
        response = client.conversations_replies(
            channel=mirror.slack_channel_id,
            ts=mirror.slack_thread_ts,
            limit=SLACK_IMPORT_PAGE_SIZE,
            cursor=cursor or None,
        )
    messages = response.get("messages") or []
    next_cursor = (response.get("response_metadata") or {}).get("next_cursor") or None
    return [m for m in messages if isinstance(m, dict)], next_cursor


@shared_task(bind=True, ignore_result=True, max_retries=3, default_retry_delay=10)
@skip_team_scope_audit  # Comment is on RootTeamManager; queries pin the team via the mirror's integration
def import_slack_thread_into_discussion(
    self: Task, comment_slack_thread_id: str, cursor: str | None = None, imported_replies: int = 0
) -> None:
    """Backfill an existing Slack thread's replies into the discussion it was imported as.

    The import action creates the mirror and the thread-root comment synchronously — validating
    that we can actually read the thread — and leaves this to pull in the reply history, which
    can be hundreds of messages and several Slack round-trips. Progress rides on the mirror's
    import_status so the UI can show the discussion filling in.

    One page per run, rescheduling itself for the next cursor, so a long thread never occupies a
    shared worker for an unbounded stretch. Idempotent per source Slack message ts: a re-run, a
    Celery retry, or a live webhook racing this backfill can't duplicate a comment.
    """
    mirror = (
        CommentSlackThread.objects.unscoped()
        .filter(id=comment_slack_thread_id)
        .select_related("integration__team")
        .first()
    )
    if mirror is None or not mirror.slack_thread_ts:
        return
    # A duplicate task delivery on an import that already settled must not reopen it.
    if mirror.import_status in SLACK_IMPORT_TERMINAL_STATUSES:
        return

    team = mirror.integration.team
    if _sync_killed(team.id):
        _set_import_state(
            mirror,
            import_status=SlackImportStatus.FAILED,
            import_error="Slack sync is turned off for this project.",
        )
        return

    _set_import_state(mirror, import_status=SlackImportStatus.IMPORTING)

    try:
        client = SlackIntegration(mirror.integration).client
        client.timeout = 10
        messages, next_cursor = _fetch_slack_thread_page(client, mirror, cursor)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            # Out of retries: settle the row rather than leaving the UI spinning forever.
            _set_import_state(
                mirror,
                import_status=SlackImportStatus.FAILED,
                import_error="PostHog couldn't finish reading the Slack thread.",
            )
            logger.warning(
                "slack_thread_import_failed", comment_slack_thread_id=comment_slack_thread_id, error=str(exc)
            )
            return
        raise self.retry(exc=exc)

    # The root message is already the discussion's thread-root comment.
    candidates = [m for m in messages if m.get("ts") and m.get("ts") != mirror.slack_thread_ts]

    # The root counts towards the cap, hence the -1: the API wrote it before enqueuing this.
    room = max(SLACK_IMPORT_MAX_MESSAGES - 1 - imported_replies, 0)
    capped = len(candidates) > room
    candidates = candidates[:room]

    # One query for the whole page instead of one per message. Re-checked implicitly by the
    # inbound webhook's own guard, which is the other writer that could land these same ts values.
    already_ingested = set(
        Comment.objects.filter(team_id=team.id, source_comment_id=mirror.source_comment_id)
        .filter(item_context__slack_message_ts__in=[m["ts"] for m in candidates])
        .values_list("item_context__slack_message_ts", flat=True)
    )

    # Comments are project-scoped: RootTeamMixin.save() would resolve an environment team to its
    # parent, but bulk_create skips save(), so resolve it here. Without this, replies imported into
    # a non-default environment would land on a different team than their root and never render.
    comment_team = team.parent_team or team

    user_cache: dict[str, dict] = {}
    to_create: list[Comment] = []
    created_ats: list[datetime | None] = []
    for message in candidates:
        message_ts = str(message["ts"])
        if message_ts in already_ingested:
            continue
        if slack_import_skip_reason(message):
            continue
        slack_user_id = str(message.get("user") or "")
        try:
            if slack_user_id not in user_cache:
                user_cache[slack_user_id] = resolve_slack_user(
                    client, slack_user_id, workspace=mirror.integration.integration_id or ""
                )
            fields = slack_message_to_comment_fields(
                client=client,
                integration=mirror.integration,
                team=team,
                message_ts=message_ts,
                slack_user_id=slack_user_id,
                text=str(message.get("text") or ""),
                blocks=message.get("blocks") if isinstance(message.get("blocks"), list) else None,
                files=message.get("files") if isinstance(message.get("files"), list) else None,
                user_info=user_cache[slack_user_id],
            )
        except Exception as exc:
            if self.request.retries >= self.max_retries:
                _set_import_state(
                    mirror,
                    import_status=SlackImportStatus.FAILED,
                    import_error="PostHog couldn't finish reading the Slack thread.",
                )
                return
            raise self.retry(exc=exc)
        if fields is None:
            continue
        to_create.append(
            build_slack_comment(
                team=comment_team,
                scope=mirror.scope,
                item_id=mirror.item_id,
                source_comment_id=mirror.source_comment_id,
                fields=fields,
            )
        )
        created_ats.append(slack_ts_to_datetime(message_ts))

    if to_create:
        # bulk_create deliberately skips post_save: it keeps the activity log from taking one row
        # per imported message, and is a second line of defence (after item_context.from_slack)
        # against the outbound mirror signal echoing the whole thread straight back to Slack.
        Comment.objects.bulk_create(to_create)
        _apply_slack_timestamps(to_create, created_ats)

    imported_replies += len(to_create)

    if next_cursor and not capped:
        _set_import_state(mirror, imported_message_count=1 + imported_replies)
        import_slack_thread_into_discussion.apply_async(
            (comment_slack_thread_id,),
            {"cursor": next_cursor, "imported_replies": imported_replies},
            countdown=SLACK_IMPORT_RESCHEDULE_COUNTDOWN_SECONDS,
        )
        return

    _set_import_state(
        mirror,
        import_status=SlackImportStatus.PARTIAL if capped else SlackImportStatus.COMPLETE,
        import_error=(
            f"This Slack thread is longer than {SLACK_IMPORT_MAX_MESSAGES} messages, so only the "
            f"first {SLACK_IMPORT_MAX_MESSAGES} were imported."
            if capped
            else ""
        ),
        imported_message_count=1 + imported_replies,
    )
    logger.info(
        "slack_thread_import_finished",
        team_id=team.id,
        comment_slack_thread_id=comment_slack_thread_id,
        imported_message_count=1 + imported_replies,
        capped=capped,
    )
