from django.db import transaction

from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit

RECONCILE_RETRY_OPTIONS = {
    "autoretry_for": (Exception,),
    "retry_backoff": 60,
    "retry_backoff_max": 3600,
    "retry_jitter": False,
    "max_retries": 8,
}


@shared_task(ignore_result=True, **RECONCILE_RETRY_OPTIONS)
@skip_team_scope_audit
def reconcile_organization_schedules(organization_id: str) -> None:
    from products.data_modeling.backend.logic.schedule_reconcile import reconcile_organization_dags

    reconcile_organization_dags(organization_id)


@shared_task(ignore_result=True, **RECONCILE_RETRY_OPTIONS)
@skip_team_scope_audit
def reconcile_dag_schedules_with_retry(dag_id: str, team_id: int) -> None:
    from products.data_modeling.backend.logic.schedule_reconcile import reconcile_dag_or_raise

    reconcile_dag_or_raise(dag_id, team_id)


def schedule_organization_schedule_reconcile(organization_id: str) -> None:
    """Move the organization's schedules onto its new plan's floor once the current transaction commits."""
    transaction.on_commit(lambda: reconcile_organization_schedules.delay(organization_id), robust=True)


def schedule_dag_schedule_reconcile(dag_id: str, team_id: int) -> None:
    """Apply a write to the DAG's schedules once the plan floor can be read again."""
    transaction.on_commit(lambda: reconcile_dag_schedules_with_retry.delay(dag_id, team_id), robust=True)
