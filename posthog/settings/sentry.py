import logging
import os

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.redis import RedisIntegration

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
        if path.startswith(("/batch")):
            return 0.00000001  # 0.000001%
        # Ingestion endpoints (high volume)
        elif path.startswith(("/capture", "/decide", "/track", "/s", "/e")):
            return 0.0000001  # 0.00001%
        # Probes/monitoring endpoints
        elif path.startswith(("/_health", "/_readyz", "/_livez")):
            return 0.0001  # 0.01%
        # API endpoints
        elif path.startswith(("/api")):
            return 0.01  # 1%
        else:
            # Default sample rate for HTTP requests
            return 0.001  # 0.1%

    elif op == "celery.task":
        task = sampling_context.get("celery_job", {}).get("task")
        if task == "posthog.celery.redis_heartbeat":
            return 0.001  # 0.1%
        else:
            # Default sample rate for Celery tasks
            return 0.001  # 0.1%
    else:
        # Default sample rate for everything else
        return 0.01  # 1%


def sentry_init() -> None:
    if not TEST and os.getenv("SENTRY_DSN"):
        sentry_sdk.utils.MAX_STRING_LENGTH = 10_000_000
        # https://docs.sentry.io/platforms/python/
        sentry_logging = sentry_logging = LoggingIntegration(level=logging.INFO, event_level=None)
        sentry_sdk.init(
            dsn=os.environ["SENTRY_DSN"],
            environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
            integrations=[DjangoIntegration(), CeleryIntegration(), RedisIntegration(), sentry_logging],
            request_bodies="always",
            sample_rate=1.0,
            # Configures the sample rate for error events, in the range of 0.0 to 1.0. The default is 1.0 which means that 100% of error events are sent. If set to 0.1 only 10% of error events will be sent. Events are picked randomly.
            send_default_pii=True,
            traces_sampler=traces_sampler,
        )


sentry_init()
