import itertools
import logging
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from collections.abc import Sequence

import posthoganalytics


class ParameterExtractor:
    def __init__(self, patterns: Sequence[str]) -> None:
        self._pattern = re.compile(r"\b" + r"|".join(map("({0})".format, patterns)) + r"\b")

    def extract(self, value: str) -> tuple[str, Sequence[str]]:
        counter = itertools.count()
        parameters = []

        def replace(match: re.Match) -> str:
            parameters.append(match[0])
            return f"${next(counter)}"

        return self._pattern.sub(replace, value), parameters


extractor = ParameterExtractor(
    [
        r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d+)?([+-][0-2]\d:[0-5]\d|Z)?)?",  # iso-ish date
        r"\w+(\.\w+)+",  # versions, modules, ip addresses, etc
        r"[0-9A-Fa-f]{8}(-)?[0-9A-Fa-f]{4}(-)?[0-9A-Fa-f]{4}(-)?[0-9A-Fa-f]{4}(-)?[0-9A-Fa-f]{12}",  # hex uuid, optional separators
        r"\d+(\.\d+)?",  # numeric values (integers and floats)
    ],
)


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
        distinct_id = "mykologs"

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

        message_template, message_parameters = extractor.extract(message)

        posthoganalytics.capture(
            distinct_id,
            "$log",
            {
                "$namespace": record.name,
                "$level": record.levelname,
                "$msg": message,
                "$msg:template": message_template,
                "$msg:parameters": message_parameters,
                "$process_person_profile": False,
                **self._default_properties,
                **record_properties,
            },
            timestamp=datetime.fromtimestamp(record.created),
        )
