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


def capture_exception(error=None, additional_properties=None):
    import sys
    import structlog
    from posthoganalytics import api_key, capture_exception as posthog_capture_exception

    logger = structlog.get_logger(__name__)

    from posthog.clickhouse.query_tagging import get_query_tags

    properties = get_query_tags().model_dump(exclude_none=True)

    if additional_properties:
        properties.update(additional_properties)

    properties.update(celery_properties())

    # logger.exception() uses sys.exc_info() internally, so we should check this first
    exc_info = sys.exc_info()
    has_valid_exc_info = exc_info[0] is not None

    if api_key:
        uuid = posthog_capture_exception(error, properties=properties)

        # Only log if captured
        if uuid is not None:
            if has_valid_exc_info:
                logger.exception(error, event_id=uuid)
            else:
                logger.error(
                    f"Exception captured: {error}",
                    event_id=uuid,
                    exception_type=type(error).__name__ if error else "None",
                )
    else:
        if has_valid_exc_info:
            logger.exception(error)
        else:
            logger.error(f"Exception captured: {error}", exception_type=type(error).__name__ if error else "None")
