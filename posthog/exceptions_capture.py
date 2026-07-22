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


def _is_user_input_query_error(error) -> bool:
    """Whether an exception is a benign user-input query error rather than a platform defect.

    ExposedHogQLError and user-safe ClickHouse errors mean the user's query was invalid (a missing
    field, bad syntax, ...) — they're returned to the user as 4xx, not a reliability problem. Many
    server-side entry points that run HogQL on the user's behalf (data-modeling materialization,
    alerts, endpoints, the query API's DRF error reporter) funnel through this wrapper, so
    classifying here keeps that expected noise out of error tracking in one place. Deliberately
    narrow: it mirrors QueryRunner.run's USER_ERROR bucket, so timeouts, out-of-memory, and internal
    resolver errors — which can signal real platform problems — are still captured.
    """
    if not isinstance(error, Exception):
        return False
    try:
        # Deferred import avoids an import cycle (posthog.errors -> posthog.exceptions -> here).
        from posthog.errors import QueryErrorCategory, classify_query_error  # noqa: PLC0415

        return classify_query_error(error) == QueryErrorCategory.USER_ERROR
    except Exception:
        return False


def capture_exception(error=None, additional_properties=None):
    import structlog
    from posthoganalytics import (
        api_key,
        capture_exception as posthog_capture_exception,
    )

    logger = structlog.get_logger(__name__)

    if _is_user_input_query_error(error):
        return None

    from posthog.clickhouse.query_tagging import get_query_tags

    properties = get_query_tags().model_dump(exclude_none=True)

    if additional_properties:
        properties.update(additional_properties)

    properties.update(celery_properties())

    if api_key:
        uuid = posthog_capture_exception(error, properties=properties)

        # Only log if captured
        if uuid is not None:
            logger.exception(error, event_id=uuid)
    else:
        logger.exception(error)
