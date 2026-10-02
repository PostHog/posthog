"""The shared alert configuration and its runtime state, for any source.

Enough of the shape from the implementation RFC for a source adapter to stop reading its
product's own configuration table, and no more. Fields land as adapters need them.

`Platform` rather than the bare `AlertConfiguration` and `Alert`, which the insight alert
configuration already holds in this app. The prefix names what the rows are for: an alert any
source configures on the shared platform, rather than one product's own table.
"""

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class PlatformAlertConfiguration(TeamScopedRootMixin, UUIDModel):
    """What to evaluate, how often, and against what bound.

    Evaluation-level state lives here rather than on `PlatformAlert`, because a failed check
    fails the whole evaluation rather than one group of its results.
    """

    class SourceKind(models.TextChoices):
        LOGS = "logs", "Logs"

    # No database constraint: creating one takes a lock on `posthog_team` that queues behind
    # live writes. Django still cascades in Python, which is the only path that deletes a team.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")

    # `CreatedMetaFields` is deliberately not used: its `created_by` is a foreign key to
    # `posthog_user`, and creating that constraint locks a table every request writes.
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    name = models.CharField(max_length=255)
    enabled = models.BooleanField(default=True, db_default=True)

    source_kind = models.CharField(max_length=32, choices=SourceKind.choices)
    source_config = models.JSONField(default=dict)

    threshold_count = models.PositiveIntegerField()
    threshold_operator = models.CharField(max_length=16)

    window_minutes = models.PositiveIntegerField()
    check_interval_minutes = models.PositiveIntegerField()
    evaluation_periods = models.PositiveIntegerField(default=1, db_default=1)
    datapoints_to_alarm = models.PositiveIntegerField(default=1, db_default=1)
    cooldown_minutes = models.PositiveIntegerField(default=0, db_default=0)
    schedule_restriction = models.JSONField(null=True, blank=True)

    next_check_at = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0, db_default=0)

    # The row this was copied from, so a backfill can run twice and so a comparison can line
    # an evaluation up against the one the source's own stack produced.
    legacy_configuration_id = models.UUIDField(null=True, blank=True, unique=True)

    class Meta:
        indexes = [
            # Discovery: enabled rows ordered by due time. Partial, because a disabled
            # configuration is never discovered and does not belong in the index.
            models.Index(
                fields=["next_check_at", "id"],
                name="platform_alert_cfg_due_idx",
                condition=models.Q(enabled=True),
            ),
            # One batch key's read. Equalities first, then the range, which is the order
            # `due_checks` filters in and the only order that lets all four columns be used.
            models.Index(
                fields=["team_id", "enabled", "source_kind", "next_check_at"],
                name="platform_alert_cfg_batch_idx",
            ),
        ]


class PlatformAlert(TeamScopedRootMixin, UUIDModel):
    """Runtime state for one instance of a configuration.

    `grouping_key` is empty until a source groups its results. The unique constraint is what
    makes one row per group, so grouping needs no schema change beyond writing a real key.
    """

    class State(models.TextChoices):
        NOT_FIRING = "not_firing", "Not firing"
        FIRING = "firing", "Firing"
        ERRORED = "errored", "Errored"
        SNOOZED = "snoozed", "Snoozed"
        BROKEN = "broken", "Broken"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    configuration = models.ForeignKey(PlatformAlertConfiguration, on_delete=models.CASCADE, related_name="alerts")

    grouping_key = models.CharField(max_length=255, default="", db_default="")
    state = models.CharField(max_length=32, choices=State.choices, default=State.NOT_FIRING, db_default="not_firing")
    last_notified_at = models.DateTimeField(null=True, blank=True)
    snooze_until = models.DateTimeField(null=True, blank=True)
    # Identifies one firing, from the transition into FIRING to the transition out. A timestamp
    # rather than an opaque id, because `last_notified_at >= firing_started_at` is then how a
    # reader knows whether this firing was ever announced.
    firing_started_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["configuration", "grouping_key"], name="platform_alert_one_per_group")
        ]


class PlatformAlertThread(TeamScopedRootMixin, UUIDModel):
    """One provider conversation, and what has already been said in it.

    A resolve replies under the message that fired, which needs the handle from that first send.
    One row is one conversation: the configuration, the group, the provider and the channel it
    posts to, plus the firing it belongs to. Without the firing a thread would span every
    incident an alert ever had; without the group two groups would share one.

    It also carries what makes a redelivery safe. A send that a crash left unrecorded repeats
    on retry, because no provider offers an idempotency key, so the row holds who has already
    been delivered and who is mid-send right now.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    configuration = models.ForeignKey(PlatformAlertConfiguration, on_delete=models.CASCADE, related_name="threads")

    grouping_key = models.CharField(max_length=255, default="", db_default="")
    provider = models.CharField(max_length=32)
    # A repointed destination gives a different answer, which stops a reply going to the old place.
    channel_target = models.CharField(max_length=255)
    episode_started_at = models.DateTimeField()

    # The provider's own handle, `{"channel": ..., "ts": ...}` for Slack. Opaque to everything
    # but the transport that issued it.
    external_ref = models.JSONField(default=dict)

    # Evaluations already delivered into this conversation, newest last. Capped, because a
    # thread lives as long as its firing and the list only has to outlive a retry.
    delivered_evaluation_keys = models.JSONField(default=list)

    # A send in flight. Held for `PENDING_CLAIM_TTL` so a retry that starts while the first
    # attempt is still mid-post waits rather than posting a second copy.
    pending_evaluation_key = models.CharField(max_length=255, null=True, blank=True)
    pending_claimed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["configuration", "grouping_key", "provider", "channel_target", "episode_started_at"],
                name="platform_alert_thread_one_per_conversation",
            )
        ]
