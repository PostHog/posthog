from django.db import transaction

from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit


@shared_task(ignore_result=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
@skip_team_scope_audit
def reconcile_organization_schedules(organization_id: str) -> None:
    from products.data_modeling.backend.logic.schedule_reconcile import reconcile_organization_dags

    reconcile_organization_dags(organization_id)


def schedule_organization_schedule_reconcile(organization_id: str) -> None:
    """Move the organization's schedules onto its new plan's floor once the current transaction commits."""
    transaction.on_commit(lambda: reconcile_organization_schedules.delay(organization_id), robust=True)
