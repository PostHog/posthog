from celery import shared_task

from posthog.models.scoping import with_team_scope

from products.customer_analytics.backend.facade.email_matching import (
    finish_email_thread_link_recalculation,
    recalculate_email_thread_links,
)
from products.customer_analytics.backend.logic.announcements import send_pending_deliveries
from products.customer_analytics.backend.logic.custom_property_sync import run_custom_property_sync


@shared_task(name="customer_analytics.process_custom_property_sync", ignore_result=True)
def process_custom_property_sync(team_id: int, saved_query_id: str) -> None:
    run_custom_property_sync(team_id=team_id, saved_query_id=saved_query_id)


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
