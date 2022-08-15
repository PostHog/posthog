import logging
import os

import structlog

from posthog.settings.base_variables import TEST

# Setup logging
LOGGING_FORMATTER_NAME = os.getenv("LOGGING_FORMATTER_NAME", "default")
DEFAULT_LOG_LEVEL = os.getenv("DJANGO_LOG_LEVEL", "ERROR" if TEST else "INFO")


class FilterStatsd(logging.Filter):
    def filter(self, record):
        return not record.name.startswith("statsd.client")


LOGGING = {
    "version": 1,
    "disable_existing_loggers": True,
    "formatters": {
        "default": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": structlog.dev.ConsoleRenderer(colors=False),
        },
        "json": {"()": structlog.stdlib.ProcessorFormatter, "processor": structlog.processors.JSONRenderer(),},
    },
    "filters": {"filter_statsd": {"()": "posthog.settings.logs.FilterStatsd",}},
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": LOGGING_FORMATTER_NAME,
            "filters": ["filter_statsd"],
        },
        "null": {"class": "logging.NullHandler",},
    },
    "root": {"handlers": ["console"], "level": DEFAULT_LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["console"], "level": DEFAULT_LOG_LEVEL},
        "django.server": {"handlers": ["null"]},  # blackhole Django server logs (this is only needed in DEV)
        "django.utils.autoreload": {
            "handlers": ["null"],
        },  # blackhole Django autoreload logs (this is only needed in DEV)
        "axes": {"handlers": ["console"], "level": DEFAULT_LOG_LEVEL},
    },
}


structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    context_class=structlog.threadlocal.wrap_dict(dict),
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)
