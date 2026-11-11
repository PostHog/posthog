from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit


@shared_task(ignore_result=True)
@skip_team_scope_audit
def reconcile_plan_floor_drift() -> None:
    from products.data_modeling.backend.logic.schedule_reconcile import (
        reconcile_plan_floor_drift as reconcile_drifted_dags,
    )

    reconcile_drifted_dags()
