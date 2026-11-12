from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit

CLAMP_TIME_LIMIT_SECONDS = 50 * 60


@shared_task(ignore_result=True, time_limit=CLAMP_TIME_LIMIT_SECONDS)
@skip_team_scope_audit
def clamp_targets_to_plan_floor() -> None:
    from products.data_modeling.backend.logic.schedule_reconcile import (
        clamp_targets_to_plan_floor as clamp_saved_targets,
    )

    clamp_saved_targets()
