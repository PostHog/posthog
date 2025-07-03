def capture_exception(error=None, additional_properties=None):
    from posthoganalytics import api_key, capture_exception as posthog_capture_exception
    import structlog

    logger = structlog.get_logger(__name__)

    from posthog.clickhouse.query_tagging import get_query_tags

    properties = get_query_tags().model_dump(exclude_none=True)

    if additional_properties:
        properties.update(additional_properties)

    if api_key:
        result = posthog_capture_exception(error, properties=properties)

        # Only log if captured
        if result is not None:
            log_kwargs = {}

            if isinstance(result, tuple) and len(result) == 2:
                _, msg = result
                if isinstance(msg, dict):
                    log_kwargs["event_id"] = msg.get("uuid")
            elif isinstance(result, str):
                log_kwargs["event_id"] = result

            logger.exception(error, **log_kwargs)
    else:
        logger.exception(error)
