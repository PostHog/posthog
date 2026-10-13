from datetime import UTC, datetime

import structlog
import posthoganalytics
from celery import Task, shared_task
from structlog.contextvars import bound_contextvars

from posthog.exceptions_capture import capture_exception
from posthog.models.scoping import with_team_scope

from products.customer_analytics.backend.facade.email_matching import (
    finish_email_thread_link_recalculation,
    recalculate_email_thread_links,
)
from products.customer_analytics.backend.logic.announcements import send_pending_deliveries
from products.customer_analytics.backend.logic.custom_property_sync import sync_custom_property_values
from products.customer_analytics.backend.logic.feature_request_github import process_github_issue_update

logger = structlog.get_logger(__name__)


class FeatureRequestGitHubTaskFailed(Exception):
    pass


def _delivery_age_seconds(github_received_at: str | None) -> float | None:
    if github_received_at is None:
        return None
    try:
        received_at = datetime.fromisoformat(github_received_at)
    except ValueError:
        return None
    if received_at.tzinfo is None:
        return None
    delay_seconds = (datetime.now(UTC) - received_at).total_seconds()
    return delay_seconds if delay_seconds >= 0 else None


def _capture_terminal_feature_request_github_failure(
    error: Exception,
    *,
    github_delivery_id: str | None,
    task_id: str | None,
    sync_attempt: int,
    installation_id: str,
    github_received_at: str | None,
) -> None:
    sanitized_error = FeatureRequestGitHubTaskFailed().with_traceback(error.__traceback__)
    try:
        with posthoganalytics.new_context(fresh=True, capture_exceptions=False):
            posthoganalytics.set_capture_exception_code_variables_context(False)
            try:
                raise sanitized_error from None
            except FeatureRequestGitHubTaskFailed as captured_error:
                capture_exception(
                    captured_error,
                    {
                        "github_delivery_id": github_delivery_id,
                        "task_id": task_id,
                        "sync_attempt": sync_attempt,
                        "installation_id": installation_id,
                        "github_received_at": github_received_at,
                        "exception_type": type(error).__name__,
                    },
                )
    except Exception:
        logger.warning("feature_request_github_exception_capture_failed")


@shared_task(
    name="customer_analytics.process_feature_request_github_issue",
    bind=True,
    ignore_result=True,
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_jitter=True,
)
def process_feature_request_github_issue(
    self: Task,
    installation_id: str,
    repository: str,
    issue_number: int,
    issue_title: str,
    issue_state: str,
    issue_state_reason: str,
    github_updated_at: str,
    github_delivery_id: str | None = None,
    github_received_at: str | None = None,
) -> None:
    task_id = self.request.id
    sync_attempt = self.request.retries
    with bound_contextvars(
        github_delivery_id=github_delivery_id,
        task_id=task_id,
        sync_attempt=sync_attempt,
        installation_id=installation_id,
        github_received_at=github_received_at,
    ):
        logger.info(
            "feature_request_github_task_started", delivery_age_seconds=_delivery_age_seconds(github_received_at)
        )
        try:
            process_github_issue_update(
                installation_id=installation_id,
                repository=repository,
                issue_number=issue_number,
                issue_title=issue_title,
                issue_state=issue_state,
                issue_state_reason=issue_state_reason,
                github_updated_at=datetime.fromisoformat(github_updated_at),
            )
        except Exception as error:
            if self.max_retries is not None and sync_attempt >= self.max_retries:
                _capture_terminal_feature_request_github_failure(
                    error,
                    github_delivery_id=github_delivery_id,
                    task_id=task_id,
                    sync_attempt=sync_attempt,
                    installation_id=installation_id,
                    github_received_at=github_received_at,
                )
            raise


@shared_task(name="customer_analytics.process_custom_property_sync", ignore_result=True)
def process_custom_property_sync(team_id: int, saved_query_id: str) -> None:
    try:
        sync_custom_property_values(team_id=team_id, saved_query_id=saved_query_id)
    except Exception as error:
        capture_exception(error)
        raise


@shared_task(
    name="customer_analytics.rematch_account_meetings",
    ignore_result=True,
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_jitter=True,
)
@with_team_scope()
def rematch_account_meetings(team_id: int, account_id: str) -> None:
    from products.customer_analytics.backend.logic.calendar_sync import (  # noqa: PLC0415 - defers calendar sync
        rematch_account_meetings as run_meeting_rematch,
    )

    run_meeting_rematch(team_id=team_id, account_id=account_id)


@shared_task(
    name="customer_analytics.recalculate_email_thread_account_links",
    ignore_result=True,
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_jitter=True,
)
@with_team_scope()
def recalculate_email_thread_account_links(team_id: int) -> None:
    recalculate_email_thread_links(team_id)
    finish_email_thread_link_recalculation(team_id)


@shared_task(
    name="customer_analytics.recalculate_email_thread_account_links_for_threads",
    ignore_result=True,
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_jitter=True,
)
@with_team_scope()
def recalculate_email_thread_account_links_for_threads(team_id: int, thread_ids: list[str]) -> None:
    recalculate_email_thread_links(team_id, thread_ids=thread_ids)


# autoretry_for is load-bearing: bare max_retries kwargs without it are silently inert.
@shared_task(
    name="customer_analytics.send_announcement",
    ignore_result=True,
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_jitter=True,
)
@with_team_scope()
def send_announcement(announcement_id: str, team_id: int) -> None:
    send_pending_deliveries(announcement_id, team_id)
