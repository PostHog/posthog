def capture_exception(error=None, sentry_scope=None, **sentry_scope_kwargs):
    from sentry_sdk import capture_exception as sentry_capture_exception
    from posthoganalytics import api_key, capture_exception as posthog_capture_exception

    sentry_capture_exception(error, scope=sentry_scope, **sentry_scope_kwargs)

    if api_key:
        posthog_capture_exception(error)
