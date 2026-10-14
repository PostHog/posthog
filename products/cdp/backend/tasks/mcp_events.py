from celery import shared_task


@shared_task(ignore_result=True)
def expire_mcp_event_subscriptions() -> int:
    from products.cdp.backend.mcp_events import MCPEventSubscriptions  # noqa: PLC0415 — keeps HogQL off Celery startup

    return MCPEventSubscriptions.expire()
