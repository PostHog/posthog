"""The shared alert configuration and its runtime state, for any source.

Enough of the shape from the implementation RFC for a source adapter to stop reading its
product's own configuration table, and no more. Fields land as adapters need them.

`Platform` rather than the bare `AlertConfiguration` and `Alert`, which the insight alert
configuration already holds in this app. The prefix names what the rows are for: an alert any
source configures on the shared platform, rather than one product's own table.
"""

from typing import Any

from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.helpers.encrypted_fields import EncryptedJSONStringField
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.alerts_platform.backend.facade.contracts import DestinationType, Grouping
from products.alerts_platform.backend.facade.enums import (
    DeliveryPath,
    PlatformAlertCheckStatus,
    PlatformAlertConfigurationRecurrenceUnit,
    PlatformAlertConfigurationSourceKind,
    PlatformAlertOwner,
    PlatformAlertState,
)


def single_instance_grouping() -> dict[str, object]:
    return Grouping().to_stored()


# nosemgrep: tuple-return-prefer-dataclass -- Django's `choices` contract is (value, label) pairs.
def source_kind_choices() -> list[tuple[str, str]]:
    # A callable, so a new source does not write a state-only migration for its choice.
    return PlatformAlertConfigurationSourceKind.choices


class PlatformAlertConfiguration(ModelActivityMixin, TeamScopedRootMixin, UUIDModel):
    """What to evaluate, how often, and against what bound.

    Evaluation-level state lives here rather than on `PlatformAlert`, because a failed check
    fails the whole evaluation rather than one group of its results.
    """

    # The facade owns the vocabulary, because presentation needs the same list and may not
    # import this module. The attribute stays so `PlatformAlertConfiguration.SourceKind` reads
    # the way every other model in the repo does.
    SourceKind = PlatformAlertConfigurationSourceKind
    RecurrenceUnit = PlatformAlertConfigurationRecurrenceUnit
    Owner = PlatformAlertOwner
    CheckStatus = PlatformAlertCheckStatus

    # No database constraint: creating one takes a lock on `posthog_team` that queues behind
    # live writes. Django still cascades in Python, which is the only path that deletes a team.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")

    # `CreatedMetaFields` is deliberately not used: its `created_by` is a foreign key to
    # `posthog_user`, and creating that constraint locks a table every request writes.
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    name = models.CharField(max_length=255)
    enabled = models.BooleanField(default=True, db_default=True)

    source_kind = models.CharField(max_length=32, choices=source_kind_choices)
    source_config = models.JSONField(default=dict)
    # The stored form of the facade's `Grouping`.
    grouping = models.JSONField(default=single_instance_grouping, db_default={"mode": "single", "keys": []})

    # Retired, because a source keeps its bound in `source_config["condition"]`. Nothing reads these.
    threshold_count = models.PositiveIntegerField(null=True, blank=True)
    threshold_operator = models.CharField(max_length=16, null=True, blank=True)
    window_minutes = models.PositiveIntegerField(null=True, blank=True)

    check_interval_minutes = models.PositiveIntegerField()

    # Null means the recurrence is `check_interval_minutes`. Minutes cannot express a month, and
    # DST moves the local instant a day or a week lands on, so the two take different paths.
    recurrence_unit = models.CharField(max_length=8, choices=RecurrenceUnit.choices, null=True, blank=True)
    # Local wall time, HH:MM, that a calendar recurrence lands on in the team's timezone.
    anchor_time = models.CharField(max_length=5, null=True, blank=True)
    evaluation_periods = models.PositiveIntegerField(default=1, db_default=1)
    datapoints_to_alarm = models.PositiveIntegerField(default=1, db_default=1)
    cooldown_minutes = models.PositiveIntegerField(default=0, db_default=0)
    schedule_restriction = models.JSONField(null=True, blank=True)

    next_check_at = models.DateTimeField(null=True, blank=True)
    # Mutes every instance. An instance's own snooze mutes one group, and the later of the two holds.
    snooze_until = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0, db_default=0)
    check_status = models.CharField(
        max_length=16, choices=CheckStatus.choices, default=CheckStatus.OK.value, db_default="ok"
    )
    # New groups the last check that ran turned away at `max_instances`. A failed or skipped check
    # leaves both as they were, because it measured no groups.
    overflowed_groups = models.PositiveIntegerField(default=0, db_default=0)
    # The source cut its results before admission saw them all, so more groups may have been turned away.
    overflow_is_lower_bound = models.BooleanField(default=False, db_default=False)

    # The row this was copied from, so a backfill can run twice and so a comparison can line
    # an evaluation up against the one the source's own stack produced.
    legacy_configuration_id = models.UUIDField(null=True, blank=True, unique=True)
    # When an operator switched this copy off. A write in the source never turns such a copy back
    # on, so a rollout that retires a copy keeps it retired. Only a backfill run clears it.
    switched_off_at = models.DateTimeField(null=True, blank=True)

    # The source's own row records the same owner. Only the cutover and rollback commands write
    # the two, in one transaction, so each stack can decide from its own row without reading the
    # other product's table.
    owner = models.CharField(
        max_length=16, choices=Owner.choices, default=Owner.SOURCE.value, db_default=Owner.SOURCE.value
    )
    owner_changed_at = models.DateTimeField(null=True, blank=True)
    # Which rows an alert's destinations live in: the source's HogFunctions, or `AlertDestination`.
    # Separate from `owner`, because an alert moves its evaluation first and its destinations later.
    destinations_owner = models.CharField(
        max_length=16, choices=Owner.choices, default=Owner.SOURCE.value, db_default=Owner.SOURCE.value
    )

    activity_logging_on_delete = True

    def _should_log_activity_for_update(self, **kwargs: Any) -> tuple[bool, Any]:
        # A copy its source owns is not logged, so its writes skip the read of the row before the update.
        # Backfills and source edits write those copies one row at a time.
        if self.owner != PlatformAlertOwner.PLATFORM:
            return False, None
        return super()._should_log_activity_for_update(**kwargs)

    class Meta:
        # Pinned: the name predates this app, and removing this renames a live table.
        db_table = "alerts_platformalertconfiguration"
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
            # The read API's page. `source_kind` stays out of it: the API filters that column
            # with IN, which cannot yield globally ordered rows, so including it would put
            # back the sort this index exists to remove.
            models.Index(
                fields=["team_id", "-created_at", "-id"],
                name="platform_alert_cfg_list_idx",
            ),
        ]


class PlatformAlert(TeamScopedRootMixin, UUIDModel):
    """Runtime state for one instance of a configuration.

    `grouping_key` is empty until a source groups its results. The unique constraint is what
    makes one row per group, so grouping needs no schema change beyond writing a real key.
    """

    State = PlatformAlertState

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    configuration = models.ForeignKey(PlatformAlertConfiguration, on_delete=models.CASCADE, related_name="alerts")

    grouping_key = models.CharField(max_length=255, default="", db_default="")
    state = models.CharField(
        max_length=32, choices=State.choices, default=State.NOT_FIRING.value, db_default="not_firing"
    )
    last_notified_at = models.DateTimeField(null=True, blank=True)
    snooze_until = models.DateTimeField(null=True, blank=True)
    # Identifies one firing, from the transition into FIRING to the transition out. A timestamp
    # rather than an opaque id, because `last_notified_at >= firing_started_at` is then how a
    # reader knows whether this firing was ever announced.
    firing_started_at = models.DateTimeField(null=True, blank=True)
    # The last check that returned this group. Reaping reads it to free the slot of a group that
    # stopped appearing. Null for a row no check has recorded since the column existed.
    last_seen_at = models.DateTimeField(null=True, blank=True)
    # The result labels whose values make `grouping_key`. Kept because a hashed key cannot be decoded
    # back into them.
    labels = models.JSONField(default=dict, db_default={})

    class Meta:
        db_table = "alerts_platformalert"
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
    # What the transport posted to open the conversation, so an edit to it keeps what fired and
    # changes only the current state. Opaque to everything but that transport. Null for a
    # provider that cannot edit a message it posted.
    root_message = models.JSONField(null=True, blank=True)

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
        db_table = "alerts_platformalertthread"
        constraints = [
            models.UniqueConstraint(
                fields=["configuration", "grouping_key", "provider", "channel_target", "episode_started_at"],
                name="platform_alert_thread_one_per_conversation",
            )
        ]


class PlatformAlertDeliveryPath(TeamScopedRootMixin, UUIDModel):
    """The path one firing of one group delivers through, fixed by the first delivery about it.

    The path is read from the alert's destinations at send time, and those can change mid-firing.
    Without this row a firing sent through HogFunctions could resolve natively, and an incident
    manager would hold the first incident open, because the two paths key incidents differently.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    configuration = models.ForeignKey(
        PlatformAlertConfiguration, on_delete=models.CASCADE, related_name="delivery_paths"
    )

    grouping_key = models.CharField(max_length=255, default="", db_default="")
    episode_started_at = models.DateTimeField()
    path = models.CharField(max_length=16, choices=DeliveryPath.choices)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "alerts_platformalertdeliverypath"
        constraints = [
            models.UniqueConstraint(
                fields=["configuration", "grouping_key", "episode_started_at"],
                name="platform_alert_delivery_path_one_per_episode",
            )
        ]


class AlertDestination(TeamScopedRootMixin, UUIDModel):
    """Where an alert sends, for an alert whose `destinations_owner` is the platform.

    One row is one destination a person sees on the alert's page. It sends through the platform's
    transport for its type.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    configuration = models.ForeignKey(PlatformAlertConfiguration, on_delete=models.CASCADE, related_name="destinations")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    type = models.CharField(max_length=32, choices=DestinationType.choices)
    # Encrypted as one document so its value types survive a read. A webhook URL or a routing key is a credential.
    config = EncryptedJSONStringField(default=dict)
    # The transitions it sends about, as `AlertEventKind` values.
    event_kinds = ArrayField(models.CharField(max_length=16), default=list)
    enabled = models.BooleanField(default=True, db_default=True)

    consecutive_failures = models.PositiveIntegerField(default=0, db_default=0)
    disabled_reason = models.TextField(null=True, blank=True)

    # The HogFunctions this replaced, so an id issued before the move still finds the destination.
    legacy_hog_function_ids = ArrayField(models.UUIDField(), default=list, blank=True)

    class Meta:
        db_table = "alerts_platformalertdestination"
