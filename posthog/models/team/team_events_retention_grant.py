from typing import Any

from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from posthog.models.team.event_retention import reconcile_team_events_retention


class TeamEventsRetentionGrant(models.Model):
    team = models.OneToOneField(
        "posthog.Team",
        on_delete=models.CASCADE,
        primary_key=True,
        db_constraint=False,
        related_name="events_retention_grant",
    )
    retention_months = models.PositiveSmallIntegerField()
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


@receiver(post_save, sender=TeamEventsRetentionGrant)
@receiver(post_delete, sender=TeamEventsRetentionGrant)
def apply_events_retention_grant(sender: Any, instance: TeamEventsRetentionGrant, **kwargs: Any) -> None:
    reconcile_team_events_retention(instance.team)
