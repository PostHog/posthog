from django.db import transaction

from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit

RECONCILE_RETRY_OPTIONS = {
    "autoretry_for": (Exception,),
    "retry_backoff": 60,
    "retry_backoff_max": 3600,
    "retry_jitter": True,
    "max_retries": 8,
}


@shared_task(ignore_result=True, **RECONCILE_RETRY_OPTIONS)
@skip_team_scope_audit
def reconcile_dag_schedules_with_retry(dag_id: str, team_id: int) -> None:
    from products.data_modeling.backend.logic.schedule_reconcile import reconcile_dag_or_raise

    reconcile_dag_or_raise(dag_id, team_id)


def schedule_dag_schedule_reconcile(dag_id: str, team_id: int) -> None:
    """Retry applying a write to the DAG's schedules, for a reconcile that failed or couldn't confirm they match."""
    transaction.on_commit(lambda: reconcile_dag_schedules_with_retry.delay(dag_id, team_id), robust=True)
