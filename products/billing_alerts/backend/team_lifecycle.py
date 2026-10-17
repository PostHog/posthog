from __future__ import annotations

from django.db import connections, transaction
from django.db.models import F, QuerySet
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone

from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.billing_alerts.backend.models import BillingAlertConfiguration


def _replacement_team_id(*, origin: object, instance: Team, using: str) -> int | None:
    if isinstance(origin, Organization):
        return None

    teams = Team.objects.using(using).filter(organization_id=instance.organization_id)
    if isinstance(origin, QuerySet) and origin.model is Team:
        teams = teams.exclude(id__in=set(origin.using(using).values_list("id", flat=True)))
    else:
        teams = teams.exclude(id=instance.id)

    # Pick the lowest id in Python: `ORDER BY id LIMIT 1` lets the planner walk the primary key
    # and filter organization_id on every row, instead of seeking the organization index.
    return min(teams.values_list("id", flat=True), default=None)


@receiver(pre_delete, sender=Team, dispatch_uid="billing_alerts_rehome_before_team_delete")
def rehome_billing_alerts_before_team_delete(
    sender: type[Team],
    instance: Team,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    """Skip quietly when this receiver's code is deployed before its migration has run."""
    table_name = BillingAlertConfiguration._meta.db_table
    if table_name not in connections[using].introspection.table_names():
        return

    # Deferred: this receiver is connected at app start, and the facade drags the alerts
    # platform onto that path.
    from products.billing_alerts.backend.facade.api import soft_delete_destinations_for_alerts  # noqa: PLC0415

    with transaction.atomic(using=using):
        alerts = BillingAlertConfiguration.objects.using(using).select_for_update().filter(team_id=instance.id)
        alert_ids = [str(alert_id) for alert_id in alerts.values_list("id", flat=True)]
        if not alert_ids:
            return
        soft_delete_destinations_for_alerts(team_id=instance.id, alert_ids=alert_ids)
        replacement_team_id = _replacement_team_id(origin=origin, instance=instance, using=using)

        # Billing alerts evaluate organization-wide data, but HogFunction destinations are team-scoped.
        # Re-home and disable them because team-specific integrations cannot be moved safely.
        # This bulk re-home on team deletion is an administrative lifecycle reset, not a per-alert
        # evaluation transition, so it intentionally does not route through the state machine adapter.
        alerts.update(  # nosemgrep: billing-alert-state-direct-mutation
            team_id=replacement_team_id,
            enabled=False,
            state=BillingAlertConfiguration.State.NOT_FIRING,
            snoozed_until=None,
            configuration_revision=F("configuration_revision") + 1,
            pending_evaluation_date=None,
            retry_attempt_count=0,
            next_check_at=None,
            updated_at=timezone.now(),
        )
