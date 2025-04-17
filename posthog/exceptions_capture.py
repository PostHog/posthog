def capture_exception(error=None, properties=None):
    from posthoganalytics import api_key, capture_exception as posthog_capture_exception
    import structlog

    logger = structlog.get_logger(__name__)

    if api_key:
        _, msg = posthog_capture_exception(error, properties=properties)
        logger.exception(error, event_id=msg.get("uuid"))
    else:
        logger.exception(error)
