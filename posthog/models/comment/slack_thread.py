from django.db import models, transaction

from posthog.models.comment.comment import Comment
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.signals import mutable_receiver
from posthog.models.utils import UUIDModel


class CommentSlackThread(TeamScopedRootMixin, UUIDModel):
    """Maps a discussion thread to a mirrored Slack thread so replies sync both ways.

    Keyed on the thread-root comment (``source_comment``), so a single item — e.g. an
    insight — can have many independently-synced threads, each to its own Slack channel.
    ``scope`` / ``item_id`` are denormalized from the thread root so a discussion's synced
    threads can be listed without loading every comment.
    """

    # db_constraint=False: posthog_team is a hot table; a real FK constraint would lock it on
    # CREATE TABLE. Tenant isolation is enforced by the fail-closed TeamScopedManager, not the DB FK.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)

    scope = models.CharField(max_length=79)
    item_id = models.CharField(max_length=72, null=True, blank=True)
    # The thread-root comment this Slack thread mirrors. One Slack thread per discussion (1:1):
    # the OneToOne is the uniqueness guard that makes send_to_slack's get_or_create race-safe.
    source_comment = models.OneToOneField("posthog.Comment", on_delete=models.CASCADE)

    integration = models.ForeignKey(
        "posthog.Integration",
        on_delete=models.CASCADE,
        limit_choices_to={"kind": "slack"},
        help_text="Slack integration whose bot token posts to and reads from the mirrored thread",
    )
    slack_channel_id = models.CharField(max_length=255)
    # Empty until the root message is posted — the row is reserved first to win the race for this
    # (team, source_comment, channel) before any Slack call, then the ts is filled in.
    slack_thread_ts = models.CharField(max_length=255, blank=True, default="")
    # Slack workspace id, used to route inbound thread replies back to this mapping.
    slack_team_id = models.CharField(max_length=255, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    # db_constraint=False: posthog_user is a hot table (see team above).
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_index=False, db_constraint=False
    )

    class Meta:
        indexes = [
            models.Index(fields=["team_id", "scope", "item_id"]),
        ]


@mutable_receiver(models.signals.post_save, sender=Comment)
def mirror_comment_reply_to_slack_on_create(sender, instance: Comment, created: bool, **kwargs) -> None:
    """Sync a newly-created discussion reply out to any mirrored Slack threads.

    Only replies (``source_comment`` set) sync — the thread root is posted by the send_to_slack
    action. Conversations tickets are excluded (that product has its own Slack sync), and
    Slack-originated replies (``item_context.from_slack``) are skipped to avoid echo loops.
    """
    if not created or not instance.source_comment_id:
        return
    if instance.scope == "conversations_ticket":
        return
    item_context = instance.item_context
    if isinstance(item_context, dict) and item_context.get("from_slack"):
        return
    if (
        not CommentSlackThread.objects.for_team(instance.team_id)
        .filter(source_comment_id=instance.source_comment_id)
        .exists()
    ):
        return

    comment_id = str(instance.id)

    def _enqueue() -> None:
        # Deferred import: this module loads at django.setup(); keep the Slack/Celery deps off that path.
        from posthog.tasks.comment_slack_sync import mirror_comment_reply_to_slack  # noqa: PLC0415

        mirror_comment_reply_to_slack.delay(comment_id=comment_id)

    transaction.on_commit(_enqueue)
