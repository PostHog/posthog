import logging
import os
from datetime import timedelta
from random import random

import sentry_sdk
from dateutil import parser
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.redis import RedisIntegration
from sentry_sdk.integrations.clickhouse_driver import ClickhouseDriverIntegration
from posthog.git import get_git_commit_full

from posthog.settings import get_from_env
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


def before_send_transaction(event, hint):
    url_string = event.get("request", {}).get("url")
    if url_string and "decide" in url_string:
        DECIDE_SAMPLE_RATE = 0.00001  # 0.001%
        should_sample = random() < DECIDE_SAMPLE_RATE

        transaction_start_time = event.get("start_timestamp")
        transaction_end_time = event.get("timestamp")
        if transaction_start_time and transaction_end_time:
            try:
                parsed_start_time = parser.parse(transaction_start_time)
                parsed_end_time = parser.parse(transaction_end_time)

                duration = parsed_end_time - parsed_start_time

                if duration >= timedelta(seconds=8):
                    # return all events for transactions that took more than 8 seconds
                    return event
                elif duration > timedelta(seconds=2):
                    # very high sample rate for transactions that took more than 2 seconds
                    return event if random() < 0.5 else None

            except Exception:
                return event if should_sample else None

        return event if should_sample else None
    else:
        return event


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
        force_sample = bool(sampling_context.get("wsgi_environ", {}).get("HTTP_FORCE_SAMPLE"))
        if os.environ.get("SERVER_GATEWAY_INTERFACE") == "ASGI":
            path = sampling_context.get("asgi_scope", {}).get("path", "")
            headers = sampling_context.get("asgi_scope", {}).get("headers", [])
            for name, value in headers:
                if name.lower().replace(b"_", b"-") == "force-sample":
                    force_sample = bool(value)

        # HTTP header to force sampling set
        if force_sample:
            return 1.0  # 100%
        # Ingestion endpoints (high volume)
        elif path.startswith("/batch"):
            return 0.00000001  # 0.000001%
        # Ingestion endpoints (high volume)
        elif path.startswith(("/capture", "/track", "/s", "/e")):
            return 0.0000001  # 0.00001%
        # Get more traces for /decide than other high volume endpoints
        elif path.startswith("/decide"):
            # decide sampling happens in before_send_transaction,
            # where we sample on duration instead of no. of requests
            return 1.0  # 100%
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

        if task in (
            "posthog.celery.redis_heartbeat",
            "posthog.celery.redis_celery_queue_depth",
        ):
            return 0.0001  # 0.01%

        # Default sample rate for Celery tasks
        return 0.001  # 0.1%
    elif op == "queue.task.celery":
        task = sampling_context.get("celery_job", {}).get("task")
        if task == "posthog.tasks.calculate_cohort.insert_cohort_from_feature_flag":
            # sample all cohort calculations via feature flag
            return 1
        # Default sample rate
        return 0.01

    else:
        # Default sample rate for everything else
        return 0.01  # 1%


def sentry_init() -> None:
    if not TEST and os.getenv("SENTRY_DSN"):
        # Setting this on enables more visibility, at the risk of capturing personal information we should not:
        #   - standard sentry "client IP" field, through send_default_pii
        #   - django access logs (info level)
        #   - request payloads
        # See https://docs.sentry.io/platforms/python/data-collected/
        send_pii = get_from_env("SENTRY_SEND_PII", type_cast=bool, default=False)

        sentry_logging_level = logging.INFO if send_pii else logging.ERROR
        profiles_sample_rate = get_from_env("SENTRY_PROFILES_SAMPLE_RATE", type_cast=float, default=0.0)

        release = get_git_commit_full()

        sentry_sdk.init(
            send_default_pii=send_pii,
            dsn=os.environ["SENTRY_DSN"],
            release=release,
            integrations=[
                DjangoIntegration(),
                CeleryIntegration(),
                RedisIntegration(),
                ClickhouseDriverIntegration(),
                LoggingIntegration(level=sentry_logging_level, event_level=None),
            ],
            max_request_body_size="always" if send_pii else "never",
            max_value_length=8192,  # Increased from the default of 1024 to capture SQL statements in full
            sample_rate=1.0,  # Sampling rate of errors
            traces_sampler=traces_sampler,
            before_send=before_send,
            before_send_transaction=before_send_transaction,
            _experiments={
                # https://docs.sentry.io/platforms/python/profiling/
                # The profiles_sample_rate setting is relative to the traces_sample_rate setting.
                "profiles_sample_rate": profiles_sample_rate,
            },
        )


sentry_init()
