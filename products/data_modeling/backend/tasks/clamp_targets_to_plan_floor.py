from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit


@shared_task(ignore_result=True)
@skip_team_scope_audit
def clamp_targets_to_plan_floor() -> None:
    from products.data_modeling.backend.logic.schedule_reconcile import (
        clamp_targets_to_plan_floor as clamp_saved_targets,
    )

    clamp_saved_targets()
