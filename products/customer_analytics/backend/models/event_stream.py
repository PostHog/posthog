from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class EventStream(TeamScopedRootMixin, UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    """A live feed of selected customers' events, delivered to a Slack channel.

    One per user per team (``created_by`` is the owner): each team member picks their own
    channel and member accounts. Delivery happens through a managed ``template-slack``
    HogFunction destination (referenced by ``hog_function_id``) whose filters are rebuilt
    from ``event_names`` and the members' account group keys on every change.
    """

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        db_constraint=False,
        related_name="customer_analytics_event_streams",
    )
    # CASCADE, not SET_NULL: created_by is the owner, and an ownerless stream would keep
    # delivering to Slack with nobody able to manage it. The pre_delete signal (signals.py)
    # archives the managed destination on every deletion path, including this cascade.
    created_by = models.ForeignKey("posthog.User", on_delete=models.CASCADE, null=True, blank=True, db_constraint=False)

    enabled = models.BooleanField(default=False)
    event_names = models.JSONField(default=list)

    slack_integration = models.ForeignKey(
        "posthog.Integration", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    slack_channel_id = models.CharField(max_length=200, blank=True, default="")
    slack_channel_name = models.CharField(max_length=200, blank=True, default="")

    hog_function_id = models.UUIDField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "created_by"], name="unique_event_stream_per_user"),
        ]


class EventStreamMember(TeamScopedRootMixin, UUIDModel, CreatedMetaFields):
    """An account included in the team's event stream."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )

    stream = models.ForeignKey(EventStream, on_delete=models.CASCADE, related_name="members")
    account = models.ForeignKey(
        "customer_analytics.Account", on_delete=models.CASCADE, related_name="event_stream_memberships"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["stream", "account"], name="unique_event_stream_member"),
        ]
