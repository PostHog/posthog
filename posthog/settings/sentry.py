import os

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.clickhouse_driver import ClickhouseDriverIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.redis import RedisIntegration

from posthog.git import get_git_commit_full
from posthog.settings.base_variables import TEST


def before_send(event, hint):
    for exception in event.get("exception", {}).get("values", []):
        for frame in exception.get("stacktrace", {}).get("frames", []):
            args = frame.get("vars", {}).get("args", {})
            if isinstance(args, dict):
                for key in args.keys():
                    if "sensitive" in key:
                        frame["vars"]["args"][key] = "[Filtered]"

    return event


def sentry_init() -> None:
    if not TEST and os.getenv("SENTRY_DSN"):
        # Setting this on enables more visibility, at the risk of capturing personal information we should not:
        #   - standard sentry "client IP" field, through send_default_pii
        #   - django access logs (info level)
        #   - request payloads
        # See https://docs.sentry.io/platforms/python/data-collected/

        release = get_git_commit_full()

        sentry_sdk.init(
            release=release,
            integrations=[
                DjangoIntegration(),
                CeleryIntegration(),
                RedisIntegration(),
                ClickhouseDriverIntegration(),
            ],
            before_send=before_send,
        )


sentry_init()
