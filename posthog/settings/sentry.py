import logging
import os

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.redis import RedisIntegration

from posthog.settings.base_variables import TEST


def sentry_init(traces_sample_rate: float = 0.0000001) -> None:
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
            traces_sample_rate=traces_sample_rate,
            # A number between 0 and 1, controlling the percentage chance a given transaction will be sent to Sentry. (0 represents 0% while 1 represents 100%.) Applies equally to all transactions created in the app.
        )


sentry_init()
