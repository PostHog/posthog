from celery import shared_task

from posthog.celery_queues import CeleryQueue
from posthog.scoping_audit import skip_team_scope_audit

from products.cdp.backend.abuse import shadow

# `review_case` asks at most twice, and the SDK sends each ask at most twice, each up to the judge's 300-second
# request timeout. The margin covers the SDK's retry backoff, scoring the latest version with Jev, the case file and
# the capture.
REVIEW_SOFT_TIME_LIMIT_SECONDS = 2 * 2 * 300 + 120


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


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    soft_time_limit=REVIEW_SOFT_TIME_LIMIT_SECONDS,
    time_limit=REVIEW_SOFT_TIME_LIMIT_SECONDS + 60,
)
@skip_team_scope_audit
def review_hog_function_for_abuse(team_id: int, hog_function_id: str) -> None:
    # The review pulls in the Anthropic SDK, which stays out of Django startup.
    from products.cdp.backend.abuse import frontier_review  # noqa: PLC0415

    wait = frontier_review.review_when_quiet(team_id, hog_function_id)
    if wait is not None:
        queue_frontier_review(team_id, hog_function_id, wait)


def queue_frontier_review(team_id: int, hog_function_id: str, countdown: float) -> None:
    review_hog_function_for_abuse.apply_async(
        kwargs={"team_id": team_id, "hog_function_id": hog_function_id}, countdown=countdown
    )
