def capture_exception(error=None, properties=None):
    from posthoganalytics import api_key, capture_exception as posthog_capture_exception
    import structlog

    logger = structlog.get_logger(__name__)

    logger.exception(error)

    if api_key:
        posthog_capture_exception(error, properties=properties)
