import os
import logging
import threading

import structlog

from posthog.settings.base_variables import DEBUG, TEST

# Setup logging
LOGGING_FORMATTER_NAME = os.getenv("LOGGING_FORMATTER_NAME", "default")
DEFAULT_LOG_LEVEL = os.getenv("DJANGO_LOG_LEVEL", "ERROR" if TEST else "INFO")


class FilterStatsd(logging.Filter):
    def filter(self, record):
        return not record.name.startswith("statsd.client")


def add_pid_and_tid(
    logger: logging.Logger, method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    event_dict["pid"] = os.getpid()
    event_dict["tid"] = threading.get_ident()
    return event_dict


# To enable standard library logs to be formatted via structlog, we add this
# `foreign_pre_chain` to both formatters.
foreign_pre_chain: list[structlog.types.Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    add_pid_and_tid,
    structlog.stdlib.PositionalArgumentsFormatter(),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
    structlog.processors.UnicodeDecoder(),
]

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        *foreign_pre_chain,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    context_class=structlog.threadlocal.wrap_dict(dict),
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)


# Configure all logs to be handled by structlog `ProcessorFormatter` and
# rendered either as pretty colored console lines or as single JSON lines.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": True,
    "formatters": {
        "default": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": structlog.dev.ConsoleRenderer(colors=DEBUG),
            "foreign_pre_chain": foreign_pre_chain,
        },
        "json": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": structlog.processors.JSONRenderer(),
            "foreign_pre_chain": foreign_pre_chain,
        },
    },
    "filters": {
        "filter_statsd": {
            "()": "posthog.settings.logs.FilterStatsd",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": LOGGING_FORMATTER_NAME,
            "filters": ["filter_statsd"],
        },
        "null": {
            "class": "logging.NullHandler",
        },
    },
    "root": {"handlers": ["console"], "level": DEFAULT_LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["console"], "level": DEFAULT_LOG_LEVEL},
        "django.server": {"handlers": ["null"]},  # blackhole Django server logs (this is only needed in DEV)
        "django.utils.autoreload": {
            "handlers": ["null"],
        },  # blackhole Django autoreload logs (this is only needed in DEV)
        "kafka.conn": {"level": "WARN"},  # kafka-python logs are noisy
        "posthog.caching.warming": {"level": "INFO"},
        "boto3": {"level": "WARN"},  # boto3 logs are noisy
        "botocore": {"level": "WARN"},  # botocore logs are noisy
    },
}
