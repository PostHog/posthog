import logging
import os

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.redis import RedisIntegration

from posthog.settings.base_variables import TEST

if not TEST:
    if os.getenv("SENTRY_DSN"):
        sentry_sdk.utils.MAX_STRING_LENGTH = 10_000_000
        # https://docs.sentry.io/platforms/python/
        sentry_logging = sentry_logging = LoggingIntegration(level=logging.INFO, event_level=None)
        sentry_sdk.init(
            dsn=os.environ["SENTRY_DSN"],
            integrations=[DjangoIntegration(), CeleryIntegration(), RedisIntegration(), sentry_logging],
            request_bodies="always",
            send_default_pii=True,
            environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
        )
