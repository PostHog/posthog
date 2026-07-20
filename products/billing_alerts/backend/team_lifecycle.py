from __future__ import annotations

from django.db import connections, transaction
from django.db.models import QuerySet
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.alerts.backend.destinations import soft_delete_all_alert_destinations
from products.billing_alerts.backend.alert_destinations import BILLING_ALERT_EVENT_IDS
from products.billing_alerts.backend.logic.state_machine import apply_disable, apply_outcome, billing_alert_snapshot
from products.billing_alerts.backend.models import BillingAlertConfiguration


def _deleting_team_ids(*, origin: object, instance: Team, using: str) -> set[int]:
    if isinstance(origin, Organization):
        return set(
            Team.objects.using(using).filter(organization_id=instance.organization_id).values_list("id", flat=True)
        )

    if isinstance(origin, QuerySet) and origin.model is Team:
        return set(origin.using(using).values_list("id", flat=True))

    return {instance.id}


@receiver(pre_delete, sender=Team, dispatch_uid="billing_alerts_rehome_before_team_delete")
def rehome_billing_alerts_before_team_delete(
    sender: type[Team],
    instance: Team,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    table_name = BillingAlertConfiguration._meta.db_table
    if table_name not in connections[using].introspection.table_names():
        return

    deleting_team_ids = _deleting_team_ids(origin=origin, instance=instance, using=using)
    replacement_team_id = (
        Team.objects.using(using)
        .filter(organization_id=instance.organization_id)
        .exclude(id__in=deleting_team_ids)
        .order_by("id")
        .values_list("id", flat=True)
        .first()
    )

    with transaction.atomic(using=using):
        alerts = list(BillingAlertConfiguration.objects.using(using).select_for_update().filter(team_id=instance.id))
        for alert in alerts:
            soft_delete_all_alert_destinations(
                team_id=instance.id,
                alert_id=str(alert.id),
                allowed_event_ids=BILLING_ALERT_EVENT_IDS,
            )

            # Billing alerts evaluate organization-wide data, but HogFunction destinations are team-scoped.
            # Re-home and disable the alert here because team-specific integrations cannot be moved safely.
            update_fields = apply_outcome(alert, apply_disable(billing_alert_snapshot(alert)))
            alert.team_id = replacement_team_id
            alert.enabled = False
            alert.configuration_revision += 1
            alert.pending_evaluation_date = None
            alert.retry_attempt_count = 0
            alert.next_check_at = None
            alert.save(
                using=using,
                update_fields=[
                    *update_fields,
                    "team",
                    "enabled",
                    "configuration_revision",
                    "pending_evaluation_date",
                    "retry_attempt_count",
                    "next_check_at",
                    "updated_at",
                ],
            )
