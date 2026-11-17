from typing import Optional

from django.db import transaction

import requests
import structlog
from celery import shared_task

from posthog.workos_radar import RadarAttempt, RadarReportFailed, send_attempt_success

logger = structlog.get_logger(__name__)


@shared_task(
    ignore_result=True,
    autoretry_for=(RadarReportFailed, requests.ConnectionError, requests.Timeout),
    retry_backoff=True,
    max_retries=3,
)
def report_radar_attempt_success(attempt_id: str, challenge_completed: bool = False) -> None:
    send_attempt_success(attempt_id, challenge_completed)


def queue_attempt_success(attempt_id: str, challenge_completed: bool = False) -> None:
    # The report only feeds Radar's history, so a broker error must not fail the sign-up or sign-in
    try:
        report_radar_attempt_success.delay(attempt_id, challenge_completed)
    except Exception:
        logger.exception("workos_radar_success_report_not_queued")


def report_attempt_success(attempt: Optional[RadarAttempt]) -> None:
    """Report the attempt to Radar after the current transaction commits, so a rolled-back sign-up is never reported."""
    if attempt is None or not attempt.attempt_id:
        return
    transaction.on_commit(lambda: queue_attempt_success(attempt.attempt_id, attempt.challenge_completed))
