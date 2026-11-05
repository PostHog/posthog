from datetime import timedelta

from django.db import transaction
from django.utils import timezone

import structlog
from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit

RECONCILE_RETRY_OPTIONS = {
    "autoretry_for": (Exception,),
    "retry_backoff": 60,
    "retry_backoff_max": 3600,
    "retry_jitter": False,
    "max_retries": 8,
}
PENDING_RECONCILE_RETRY_AFTER = timedelta(hours=4)  # past the roughly three hours RECONCILE_RETRY_OPTIONS can take
PENDING_RECONCILE_GIVE_UP_AFTER = timedelta(days=7)

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, **RECONCILE_RETRY_OPTIONS)
@skip_team_scope_audit
def reconcile_organization_schedules(organization_id: str) -> None:
    from products.data_modeling.backend.logic.schedule_reconcile import reconcile_organization_dags
    from products.data_modeling.backend.models.pending_organization_reconcile import PendingOrganizationReconcile

    started_at = timezone.now()
    reconcile_organization_dags(organization_id)
    # A plan change recorded after the start may not have been read, so its row stays.
    PendingOrganizationReconcile.objects.filter(organization_id=organization_id, requested_at__lte=started_at).delete()


@shared_task(ignore_result=True)
@skip_team_scope_audit
def retry_pending_organization_reconciles() -> None:
    from products.data_modeling.backend.models.pending_organization_reconcile import PendingOrganizationReconcile

    now = timezone.now()
    expired = PendingOrganizationReconcile.objects.filter(first_requested_at__lt=now - PENDING_RECONCILE_GIVE_UP_AFTER)
    for organization_id in expired.values_list("organization_id", flat=True):
        logger.error("Gave up reconciling an organization's schedules", organization_id=str(organization_id))
    expired.delete()

    retry_before = now - PENDING_RECONCILE_RETRY_AFTER
    pending = PendingOrganizationReconcile.objects.filter(requested_at__lt=retry_before)
    for organization_id in pending.values_list("organization_id", flat=True):
        reconcile_organization_schedules.delay(str(organization_id))
        # Moved forward so the next sweep doesn't start a second chain of retries beside this one.
        PendingOrganizationReconcile.objects.filter(
            organization_id=organization_id, requested_at__lt=retry_before
        ).update(requested_at=now)


@shared_task(ignore_result=True, **RECONCILE_RETRY_OPTIONS)
@skip_team_scope_audit
def reconcile_dag_schedules_with_retry(dag_id: str, team_id: int) -> None:
    from products.data_modeling.backend.logic.schedule_reconcile import reconcile_dag_or_raise

    reconcile_dag_or_raise(dag_id, team_id)


def schedule_organization_schedule_reconcile(organization_id: str) -> None:
    """Move the organization's schedules onto its new plan's floor once the current transaction commits.

    Call it in the transaction that stores the plan, so the plan and the record of this request commit together.
    """
    from products.data_modeling.backend.models.pending_organization_reconcile import PendingOrganizationReconcile

    now = timezone.now()
    PendingOrganizationReconcile.objects.update_or_create(
        organization_id=organization_id, defaults={"requested_at": now, "first_requested_at": now}
    )
    transaction.on_commit(lambda: reconcile_organization_schedules.delay(organization_id), robust=True)


def schedule_dag_schedule_reconcile(dag_id: str, team_id: int) -> None:
    """Apply a write to the DAG's schedules once the plan floor can be read again."""
    transaction.on_commit(lambda: reconcile_dag_schedules_with_retry.delay(dag_id, team_id), robust=True)
