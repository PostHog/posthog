from posthog.clickhouse.query_tagging import get_query_tags


def capture_exception(error=None, additional_properties=None):
    from posthoganalytics import api_key, capture_exception as posthog_capture_exception
    import structlog

    logger = structlog.get_logger(__name__)

    properties = get_query_tags()

    if additional_properties:
        properties.update(additional_properties)

    if api_key:
        _, msg = posthog_capture_exception(error, properties=properties)

        log_kwargs = {}
        if isinstance(msg, dict):
            log_kwargs["event_id"] = msg.get("uuid")

        logger.exception(error, **log_kwargs)
    else:
        logger.exception(error)
