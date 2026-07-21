from celery import shared_task

from products.customer_analytics.backend.logic.custom_property_sync import run_custom_property_sync


@shared_task(name="customer_analytics.process_custom_property_sync", ignore_result=True)
def process_custom_property_sync(team_id: int, saved_query_id: str) -> None:
    run_custom_property_sync(team_id=team_id, saved_query_id=saved_query_id)
