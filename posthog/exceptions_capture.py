def capture_exception(error=None, sentry_scope=None, **sentry_scope_kwargs):
    from sentry_sdk import capture_exception as sentry_capture_exception
    from posthoganalytics import api_key, capture_exception as posthog_capture_exception
    import structlog

    logger = structlog.get_logger(__name__)

    sentry_capture_exception(error, scope=sentry_scope, **sentry_scope_kwargs)

    logger.exception(error)

    if api_key:
        posthog_capture_exception(error)
