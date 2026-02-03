def celery_properties() -> dict:
    try:
        from celery import current_task

        task = current_task
        if task and task.request and task.request.id is not None:
            return {
                "celery_task_name": task.name,
                "celery_task_retries": task.request.retries,
            }
    except Exception:
        pass
    return {}


def _in_temporal_activity() -> bool:
    """Check if we're currently running inside a Temporal activity."""
    try:
        from temporalio import activity

        return activity.in_activity()
    except Exception:
        return False


def capture_exception(error=None, additional_properties=None):
    import structlog

    from posthog.clickhouse.query_tagging import get_query_tags

    logger = structlog.get_logger(__name__)

    properties = get_query_tags().model_dump(exclude_none=True)

    if additional_properties:
        properties.update(additional_properties)

    properties.update(celery_properties())

    # In Temporal activities, use background capture to avoid blocking the event loop.
    # The posthoganalytics SDK with sync_mode=True makes blocking HTTP calls that can
    # prevent heartbeat coroutines from being processed, causing TimeoutError.
    if _in_temporal_activity():
        from posthog.temporal.common.posthog_analytics import capture_exception_in_background

        capture_exception_in_background(error, properties=properties)
        logger.exception(error)
        return

    from posthoganalytics import (
        api_key,
        capture_exception as posthog_capture_exception,
    )

    if api_key:
        uuid = posthog_capture_exception(error, properties=properties)

        # Only log if captured
        if uuid is not None:
            logger.exception(error, event_id=uuid)
    else:
        logger.exception(error)
