from django.db import models
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.signals import mutable_receiver

from posthog.models.utils import UUIDModel

# NOTE: This model is meant to be loosely related to the `activity_log` as they are similar in function and approach


class Comment(UUIDModel):
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    content: models.TextField = models.TextField(blank=True, null=True)
    version: models.IntegerField = models.IntegerField(default=0)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(null=True, blank=True, default=False)

    # Loose relationship modelling to other PostHog resources
    item_id = models.CharField(max_length=72, null=True)
    item_context = models.JSONField(null=True)
    scope = models.CharField(max_length=79, null=False)

    # Threads/replies are simply comments with a source_comment_id
    source_comment_id: models.ForeignKey = models.ForeignKey("Comment", on_delete=models.CASCADE, null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["team_id", "scope", "item_id"])]


@mutable_receiver(models.signals.post_save, sender=Comment)
def log_comment_activity(sender, instance: Comment, created: bool, **kwargs):
    if created:
        # TRICKY: - Commments relate to a "thing" like a flag or insight. When we log the activity we need to know what the "thing" is
        # to store the name that should be displayed. Rather than lookup the item every time, we

        # TODO: Ensure we got this right, people should get notified when
        # 1. A comment is placed on something they are interested in
        # 2. A comment is in reply to a thread they started (for now)
        # 3. A comment includes a @mention of them
        log_activity(
            organization_id=None,
            team_id=instance.team_id,
            user=instance.created_by,
            item_id=instance.item_id,
            scope=instance.scope,
            activity="commented",
            # TODO: Check with Paul if this is right
            detail=Detail(
                name=instance.content,
                changes=[Change(type="Comment", field="content", action="created", after=instance.content)],
            ),
        )
