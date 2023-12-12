from django.db import models
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.signals import mutable_receiver

from posthog.models.utils import UUIDModel

# NOTE: This model is meant to be loosely related to the `activity_log` as they are similar in function and approach


class Comment(UUIDModel):
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    content: models.TextField = models.TextField(blank=True, null=True)
    deleted_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    version: models.IntegerField = models.IntegerField(default=0)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)

    # Loose relationship modelling to other PostHog resources
    item_id = models.fields.CharField(max_length=72, null=True)
    scope = models.fields.CharField(max_length=79, null=False)

    # TODO: How do we allow comments to exist on individual elements such as a line in a Notebook?
    # Maybe the right way is to create a Mark in a notebook and then have that store the CommentID, keeping the comments clean

    # Threads/replies are simply comments with a source_comment_id
    source_comment_id: models.ForeignKey = models.ForeignKey("Comment", on_delete=models.CASCADE, null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["team_id", "scope", "item_id"])]


@mutable_receiver(models.signals.post_save, sender=Comment)
def log_comment_activity(sender, instance: Comment, created: bool, **kwargs):
    if created:
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
