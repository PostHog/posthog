import structlog
from celery import shared_task

from posthog.helpers.slack_thread_mirror import post_comment_to_slack_thread, slack_author_from_user
from posthog.models.comment import Comment, CommentSlackThread
from posthog.models.integration import SlackIntegration

logger = structlog.get_logger(__name__)


@shared_task(bind=True, ignore_result=True, max_retries=3, default_retry_delay=5)
def mirror_comment_reply_to_slack(self, comment_id: str) -> None:
    """Post a newly-created discussion reply into its parent's mirrored Slack thread.

    A discussion mirrors to exactly one Slack thread (1:1), so this posts to that single thread and
    retries on a Slack failure rather than silently dropping the reply.
    """
    comment = Comment.objects.filter(id=comment_id).first()
    if comment is None or not comment.source_comment_id:
        return

    mirror = (
        CommentSlackThread.objects.for_team(comment.team_id)
        .filter(source_comment_id=comment.source_comment_id)
        .select_related("integration")
        .first()
    )
    if mirror is None or not mirror.slack_thread_ts:
        return

    author_name, author_email = slack_author_from_user(comment.created_by)
    try:
        client = SlackIntegration(mirror.integration).client
        post_comment_to_slack_thread(
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


@shared_task(ignore_result=True)
def backfill_comment_slack_thread(comment_slack_thread_id: str) -> None:
    """Post a discussion's pre-existing replies into a freshly-mirrored Slack thread.

    Runs once, asynchronously, after send_to_slack — so the request isn't blocked on N sequential
    Slack posts. Best-effort per reply: a transient failure on one reply is logged and skipped
    rather than failing the whole task, so it never double-posts earlier replies. Replies created
    after the mirror exists are handled by the live post_save signal instead.
    """
    mirror = (
        CommentSlackThread.objects.unscoped().filter(id=comment_slack_thread_id).select_related("integration").first()
    )
    if mirror is None or not mirror.source_comment_id or not mirror.slack_thread_ts:
        return

    try:
        client = SlackIntegration(mirror.integration).client
    except Exception:
        logger.warning("comment_slack_backfill_client_failed", comment_slack_thread_id=comment_slack_thread_id)
        return

    # source_comment_id matches the thread root, so this returns its replies (not the root itself).
    replies = Comment.objects.filter(
        team_id=mirror.team_id, source_comment_id=mirror.source_comment_id, deleted=False
    ).order_by("created_at")
    for reply in replies:
        if isinstance(reply.item_context, dict) and reply.item_context.get("from_slack"):
            continue
        author_name, author_email = slack_author_from_user(reply.created_by)
        try:
            post_comment_to_slack_thread(
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
