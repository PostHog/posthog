from typing import cast

from django.db import models

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.activity_logging.model_activity import get_was_impersonated
from posthog.models.signals import mutable_receiver
from posthog.models.utils import RootTeamMixin, UUIDTModel

# NOTE: This model is meant to be loosely related to the `activity_log` as they are similar in function and approach


class Comment(UUIDTModel, RootTeamMixin):
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    content = models.TextField(blank=True, null=True)
    rich_content = models.JSONField(blank=True, null=True)
    version = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted = models.BooleanField(null=True, blank=True, default=False)

    # Loose relationship modelling to other PostHog resources
    item_id = models.CharField(max_length=72, null=True)
    item_context = models.JSONField(null=True)
    scope = models.CharField(max_length=79, null=False)

    # Threads/replies are simply comments with a source_comment_id
    source_comment = models.ForeignKey("Comment", on_delete=models.CASCADE, null=True, blank=True)

    # Nullable so old code can INSERT without naming the column during rolling deploys.
    is_task = models.BooleanField(null=True, blank=True, default=False)
    completed_at = models.DateTimeField(blank=True, null=True)
    completed_by = models.ForeignKey(
        "User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        db_index=False,
    )

    class Meta:
        indexes = [
            models.Index(fields=["team_id", "scope", "item_id"]),
            # Optimized for conversations polling: filters deleted=False, orders by -created_at
            models.Index(
                fields=["team_id", "scope", "item_id", "deleted", "-created_at"],
                name="posthog_comment_convo_idx",
            ),
        ]


def activity_log_scope_for(comment: Comment) -> str:
    # Map legacy "recording" → "Replay"; replies are logged under the parent thread.
    corrected = "Replay" if comment.scope == "recording" else comment.scope
    return "Comment" if comment.source_comment_id else corrected


@mutable_receiver(models.signals.post_save, sender=Comment)
def log_comment_activity(sender, instance: Comment, created: bool, **kwargs):
    if created:
        # TRICKY: - Comments relate to a "thing" like a flag or insight. When we log the activity we need to know what the "thing" is

        # Rendering in the frontend we need
        # 1. The comment content
        # 2. The resource commented on (title, link)

        # For filtering important changes we need to know
        # 1. The thing that was commented on (Ben commented on your insight/1234) - NOTE: We don't have the short_id here...
        # 2. The reply thread (Paul replied to your comment on insight/1234)
        # 3. Persons mentioned in the comment (@Ben mentioned you in insight/1234)

        # Options:
        # 1. Pass the information when commenting needed for the activity log (title, link)
        # 2. Lookup the information when loading the activity (could be pretty slow as well as needing custom logic for each type of thing)
        # 3. Pass only the URL which allows us to say "X commented on insight/1234"

        item_id = cast(str, instance.source_comment_id) or instance.item_id
        scope = activity_log_scope_for(instance)
        activity = "created task" if instance.is_task else "commented"

        log_activity(
            organization_id=None,
            team_id=instance.team_id,
            user=instance.created_by,
            was_impersonated=get_was_impersonated(),
            item_id=item_id,
            scope=scope,
            activity=activity,
            detail=Detail(
                # name=TODO,
                # short_id=TODO,
                changes=[Change(type="Comment", field="content", action="created", after=instance.content)],
            ),
        )
