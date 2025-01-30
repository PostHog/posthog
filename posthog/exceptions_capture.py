def capture_exception(error=None, sentry_scope=None, **sentry_scope_kwargs):
    from sentry_sdk import capture_exception as sentry_capture_exception
    from posthoganalytics import capture_exception as posthog_capture_exception
    from posthog.settings import TEST

    sentry_capture_exception(error, scope=sentry_scope, **sentry_scope_kwargs)

    if not TEST:
        posthog_capture_exception(error)
