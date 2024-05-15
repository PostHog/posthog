import logging
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import posthoganalytics


class PosthogHandler(logging.Handler):
    """
    Forward log records as log events to PostHog.
    """

    def __init__(self, level=logging.NOTSET, default_properties: Mapping[str, Any] | None = None):
        super().__init__(level)
        self._default_properties = default_properties if default_properties is not None else {}

    def emit(self, record: logging.LogRecord) -> None:
        # TODO: need to stash the user ID on the request and grab it rather than
        # just filling with a garbage value
        distinct_id = uuid.uuid1().hex

        # XXX: structlog specific processing -- not generically applicable to
        # all log record types; probably would want to keep this independent of
        # any generic handler instead of branching here
        if isinstance(record.msg, Mapping):
            message = record.msg["event"]
            record_properties = {
                k: v for k, v in record.msg.items() if k not in {"logger", "timestamp", "event", "level"}
            }
        else:
            message = record.getMessage()
            record_properties = {}

        posthoganalytics.capture(
            distinct_id,
            "$log",
            {
                "$namespace": record.name,
                "$level": record.levelname,
                "$msg": message,
                **self._default_properties,
                **record_properties,
            },
            timestamp=datetime.fromtimestamp(record.created),
        )
