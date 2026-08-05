from celery import shared_task

from posthog.models.scoping import with_team_scope

from products.customer_analytics.backend.logic.announcements import send_pending_deliveries
from products.customer_analytics.backend.logic.custom_property_sync import run_custom_property_sync


@shared_task(name="customer_analytics.process_custom_property_sync", ignore_result=True)
def process_custom_property_sync(team_id: int, saved_query_id: str) -> None:
    run_custom_property_sync(team_id=team_id, saved_query_id=saved_query_id)


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
