from django.db import transaction

import structlog
from celery import shared_task
from redis.exceptions import RedisError

from posthog.plugins.plugin_server_api import reload_hog_functions_on_workers

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, autoretry_for=(RedisError,), retry_backoff=True, retry_jitter=True, max_retries=5)
def retry_mcp_destination_reload(team_id: int, hog_function_ids: list[str]) -> None:
    reload_hog_functions_on_workers(team_id=team_id, hog_function_ids=hog_function_ids)


def reload_mcp_destinations_after_commit(*, team_id: int, hog_function_ids: list[str]) -> None:
    def publish() -> None:
        try:
            reload_hog_functions_on_workers(team_id=team_id, hog_function_ids=hog_function_ids)
        except RedisError:
            logger.warning("mcp_destination_reload_deferred", team_id=team_id)
            retry_mcp_destination_reload.apply_async(
                kwargs={"team_id": team_id, "hog_function_ids": hog_function_ids}, countdown=1
            )

    transaction.on_commit(publish, robust=True)


@shared_task(ignore_result=True)
def expire_mcp_event_subscriptions() -> int:
    from products.cdp.backend.mcp_events import MCPEventSubscriptions  # noqa: PLC0415 — keeps HogQL off Celery startup

    return MCPEventSubscriptions.expire()
