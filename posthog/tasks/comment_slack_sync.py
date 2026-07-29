import structlog
import posthoganalytics
from celery import shared_task

from posthog.helpers.slack_thread_mirror import post_comment_to_slack_thread, slack_author_from_user
from posthog.models.comment import Comment, CommentSlackThread
from posthog.models.comment.slack_thread import DISCUSSIONS_SLACK_SYNC_FLAG
from posthog.models.integration import SlackIntegration

logger = structlog.get_logger(__name__)

# item_context key holding the Slack ts of a reply's mirrored copy. Its presence is the
# idempotency marker that keeps Celery retries and backfill re-runs from double-posting.
SLACK_SYNCED_TS_KEY = "slack_synced_ts"


def _sync_killed(team_id: int) -> bool:
    """Kill switch for syncing on existing mirrors: only an explicit flag *off* halts it.

    The fail-closed creation gate is send_to_slack; here a flag-evaluation error or missing
    flag (None) must not silently drop user replies, so only False stops the sync.
    """
    try:
        return posthoganalytics.feature_enabled(DISCUSSIONS_SLACK_SYNC_FLAG, str(team_id)) is False
    except Exception:
        return False


def _mark_reply_synced(reply: Comment, ts: object) -> None:
    item_context = dict(reply.item_context) if isinstance(reply.item_context, dict) else {}
    item_context[SLACK_SYNCED_TS_KEY] = ts if isinstance(ts, str) else ""
    Comment.objects.filter(id=reply.id).update(item_context=item_context)


def _reply_skip_reason(reply: Comment) -> str | None:
    item_context = reply.item_context if isinstance(reply.item_context, dict) else {}
    if item_context.get("from_slack"):
        return "from_slack"  # came in from Slack — echoing it back would loop
    if item_context.get("is_emoji"):
        return "emoji"  # reactions are stored as reply comments but aren't messages
    if SLACK_SYNCED_TS_KEY in item_context:
        return "already_synced"
    return None


@shared_task(bind=True, ignore_result=True, max_retries=3, default_retry_delay=5)
def mirror_comment_reply_to_slack(self, comment_id: str) -> None:
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
        )
    except Exception as exc:
        raise self.retry(exc=exc)
    _mark_reply_synced(comment, posted_ts)


@shared_task(ignore_result=True)
def backfill_comment_slack_thread(comment_slack_thread_id: str) -> None:
    """Post a discussion's pre-existing replies into a freshly-mirrored Slack thread.

    Runs once, asynchronously, after send_to_slack — so the request isn't blocked on N sequential
    Slack posts. Bounded to replies created before the mirror: later replies belong exclusively to
    the live post_save signal, so the two paths can't both post the same reply. Best-effort per
    reply — a failure on one is logged and skipped — and each success is stamped with its posted
    ts, so a re-run never double-posts.
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

    # source_comment_id matches the thread root, so this returns its replies (not the root itself).
    replies = (
        Comment.objects.filter(
            team_id=mirror.team_id,
            source_comment_id=mirror.source_comment_id,
            deleted=False,
            created_at__lt=mirror.created_at,
        )
        .select_related("created_by")
        .order_by("created_at")
    )
    for reply in replies:
        if _reply_skip_reason(reply):
            continue
        author_name, author_email = slack_author_from_user(reply.created_by)
        try:
            posted_ts = post_comment_to_slack_thread(
                client=client,
                channel=mirror.slack_channel_id,
                content=reply.content or "",
                rich_content=reply.rich_content,
                author_name=author_name,
                author_email=author_email,
                thread_ts=mirror.slack_thread_ts,
            )
        except Exception:
            logger.warning(
                "comment_slack_backfill_reply_failed",
                comment_slack_thread_id=comment_slack_thread_id,
                comment_id=str(reply.id),
            )
            continue
        _mark_reply_synced(reply, posted_ts)
