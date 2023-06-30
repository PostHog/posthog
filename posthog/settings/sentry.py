import logging
import os

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.redis import RedisIntegration

from posthog.settings import get_from_env
from posthog.settings.base_variables import TEST


def traces_sampler(sampling_context: dict) -> float:
    #
    # Examine provided context data (including parent decision, if any)
    # along with anything in the global namespace to compute the sample rate
    # or sampling decision for this transaction.
    #
    # Please use a number between 0 and 1 (0 represents 0% while 1 represents 100%)
    #
    transaction_context = sampling_context.get("transaction_context")
    if transaction_context is None:
        return 0

    op = transaction_context.get("op")

    if op == "http.server":
        path = sampling_context.get("wsgi_environ", {}).get("PATH_INFO")

        # Ingestion endpoints (high volume)
        if path.startswith("/batch"):
            return 0.00000001  # 0.000001%
        # Ingestion endpoints (high volume)
        elif path.startswith(("/capture", "/track", "/s", "/e")):
            return 0.0000001  # 0.00001%
        # Get more traces for /decide than other high volume endpoints
        elif path.startswith("/decide"):
            return 0.00001  # 0.001%
        # Probes/monitoring endpoints
        elif path.startswith(("/_health", "/_readyz", "/_livez")):
            return 0.00001  # 0.001%
        # API endpoints
        elif path.startswith("/api/projects") and path.endswith("/persons/"):
            return 0.00001  # 0.001%
        elif path.startswith("/api/persons/"):
            return 0.00001  # 0.001%
        elif path.startswith("/api/feature_flag"):
            return 0.00001  # 0.001%
        elif path.startswith("/api/projects") and ("dashboard" in path or "insight" in path) and "timing" not in path:
            return 0.001  # 0.1%
        elif path.startswith("/api/projects") and path.endswith("/query/"):
            return 0.001  # 0.1%
        elif path.startswith("/api"):
            return 0.001  # 0.1%
        else:
            # Default sample rate for HTTP requests
            return 0.0001  # 0.01%

    elif op == "celery.task":
        task = sampling_context.get("celery_job", {}).get("task")
        if task == "posthog.celery.redis_heartbeat":
            return 0.0001  # 0.01%
        if task == "posthog.celery.redis_celery_queue_depth":
            return 0.0001  # 0.01%
        else:
            # Default sample rate for Celery tasks
            return 0.001  # 0.1%
    else:
        # Default sample rate for everything else
        return 0.01  # 1%


def sentry_init() -> None:
    if not TEST and os.getenv("SENTRY_DSN"):
        sentry_sdk.utils.MAX_STRING_LENGTH = 10_000_000

        # Setting this on enables more visibility, at the risk of capturing personal information we should not:
        #   - standard sentry "client IP" field, through send_default_pii
        #   - django access logs (info level)
        #   - request payloads
        # See https://docs.sentry.io/platforms/python/data-collected/
        send_pii = get_from_env("SENTRY_SEND_PII", type_cast=bool, default=False)

        sentry_logging_level = logging.INFO if send_pii else logging.ERROR
        sentry_logging = LoggingIntegration(level=sentry_logging_level, event_level=None)
        profiles_sample_rate = get_from_env("SENTRY_PROFILES_SAMPLE_RATE", type_cast=float, default=0.0)

        sentry_sdk.init(
            send_default_pii=send_pii,
            dsn=os.environ["SENTRY_DSN"],
            integrations=[DjangoIntegration(), CeleryIntegration(), RedisIntegration(), sentry_logging],
            request_bodies="always" if send_pii else "never",
            sample_rate=1.0,
            # Configures the sample rate for error events, in the range of 0.0 to 1.0 (default).
            # If set to 0.1 only 10% of error events will be sent. Events are picked randomly.
            traces_sampler=traces_sampler,
            _experiments={
                # https://docs.sentry.io/platforms/python/profiling/
                # The profiles_sample_rate setting is relative to the traces_sample_rate setting.
                "profiles_sample_rate": profiles_sample_rate,
            },
        )


sentry_init()
