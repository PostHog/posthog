from celery import shared_task

from posthog.celery_queues import CeleryQueue
from posthog.scoping_audit import skip_team_scope_audit

from products.cdp.backend.abuse import shadow


# A gateway or capture slowdown holds a worker for the full timeout, so this stays off the default queue.
@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
@skip_team_scope_audit
def classify_hog_function_for_abuse(
    team_id: int,
    hog_function_id: str,
    # Accepted and ignored so that workers already run this release before producers send it.
    # During a rolling deploy, a worker on an older release raises TypeError on an unknown keyword.
    enabled_content_hash: str | None = None,
) -> None:
    hog_function = shadow.scorable_hog_functions(enabled_only=False).filter(team_id=team_id, id=hog_function_id).first()
    if hog_function is not None:
        shadow.classify_if_due(hog_function)


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
@skip_team_scope_audit
def backfill_hog_function_abuse_score(team_id: int, hog_function_id: str, run_id: str) -> None:
    hog_function = shadow.scorable_hog_functions().filter(team_id=team_id, id=hog_function_id).first()
    if hog_function is not None:
        shadow.classify_for_backfill(hog_function, run_id)
