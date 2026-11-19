from typing import Optional

from django.db import transaction

import requests
import structlog
from celery import Task, shared_task

from posthog.workos_radar import RadarAttempt, RadarReportFailed, send_attempt_success

logger = structlog.get_logger(__name__)


_RETRY_BASE_SECONDS = 60
_RETRY_MAX_SECONDS = 900


def retry_countdown(retries: int, retry_after: Optional[int]) -> int:
    if retry_after is not None:
        return retry_after
    return min(_RETRY_BASE_SECONDS * 2**retries, _RETRY_MAX_SECONDS)


@shared_task(bind=True, ignore_result=True, max_retries=5)
def report_radar_attempt_success(self: Task, attempt_id: str, challenge_completed: bool = False) -> None:
    try:
        send_attempt_success(attempt_id, challenge_completed)
    except (RadarReportFailed, requests.ConnectionError, requests.Timeout) as error:
        retry_after = error.retry_after if isinstance(error, RadarReportFailed) else None
        raise self.retry(exc=error, countdown=retry_countdown(self.request.retries, retry_after))


def queue_attempt_success(attempt_id: str, challenge_completed: bool = False) -> None:
    # Publishing tries the broker once, so a stalled broker cannot hold up the sign-up or sign-in
    try:
        report_radar_attempt_success.apply_async(args=(attempt_id, challenge_completed), retry=False)
    except Exception:
        logger.exception("workos_radar_success_report_not_queued")


def report_attempt_success(attempt: Optional[RadarAttempt]) -> None:
    """Report the attempt to Radar after the current transaction commits, so a rolled-back sign-up is never reported."""
    if attempt is None or not attempt.attempt_id:
        return
    transaction.on_commit(lambda: queue_attempt_success(attempt.attempt_id, attempt.challenge_completed))
