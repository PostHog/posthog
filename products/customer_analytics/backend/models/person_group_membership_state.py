from django.db import models

from posthog.models.scoping.manager import TeamScopedManager


class PersonGroupMembershipStatus(models.TextChoices):
    PENDING_CONFIG = "pending_config", "pending_config"
    BACKFILLING = "backfilling", "backfilling"
    CATCHING_UP = "catching_up", "catching_up"
    READY = "ready", "ready"
    FAILED = "failed", "failed"
    DISABLED = "disabled", "disabled"


class PersonGroupMembershipState(models.Model):
    team = models.OneToOneField(
        "posthog.Team", primary_key=True, on_delete=models.CASCADE, db_constraint=False, related_name="+"
    )
    status = models.CharField(
        max_length=20, choices=PersonGroupMembershipStatus.choices, default=PersonGroupMembershipStatus.PENDING_CONFIG
    )
    group_type_index = models.PositiveSmallIntegerField(null=True, blank=True)
    config_version = models.PositiveBigIntegerField(default=0)
    config_written_at = models.DateTimeField(null=True, blank=True)
    historical_start = models.DateTimeField(null=True, blank=True)
    historical_end = models.DateTimeField(null=True, blank=True)
    next_window_start = models.DateTimeField(null=True, blank=True)
    catchup_end = models.DateTimeField(null=True, blank=True)
    catchup_next_window_start = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=200, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    # Membership tracks each environment's events, so never rewrite this key to its parent project.
    objects = TeamScopedManager()
