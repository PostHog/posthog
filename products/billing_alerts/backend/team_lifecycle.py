from __future__ import annotations

from django.db import connections
from django.db.models import F
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone

from posthog.models.team.team import Team

from products.billing_alerts.backend.models import BillingAlertConfiguration


@receiver(pre_delete, sender=Team, dispatch_uid="billing_alerts_rehome_before_team_delete")
def disable_billing_alerts_before_team_delete(
    sender: type[Team],
    instance: Team,
    using: str,
    **kwargs: object,
) -> None:
    """Skip quietly when this receiver's code is deployed before its migration has run."""
    table_name = BillingAlertConfiguration._meta.db_table
    if table_name not in connections[using].introspection.table_names():
        return

    BillingAlertConfiguration.objects.using(using).filter(team_id=instance.id).update(
        team_id=None,
        enabled=False,
        state=BillingAlertConfiguration.State.NOT_FIRING,
        configuration_revision=F("configuration_revision") + 1,
        snoozed_until=None,
        pending_evaluation_date=None,
        retry_attempt_count=0,
        next_check_at=None,
        updated_at=timezone.now(),
    )
