"""Batch export defaults for the shared Arrow pipeline in `posthog.temporal.common.arrow_pipeline`.

The shared pipeline knows nothing about PostHog events, so batch exports passes these values to it.
Keep this module light: JSONL worker processes import it to run `strip_web_vitals_nested_elements`.
"""

import typing

from posthog.temporal.common.logger import get_write_only_logger

LOGGER = get_write_only_logger(__name__)

EVENTS_JSON_COLUMNS: tuple[str, ...] = ("properties", "person_properties", "set", "set_once")

# A control column that the internal stage adds to every record. Most destinations do not write it.
INSERTED_AT_COLUMN = "_inserted_at"


def strip_web_vitals_nested_elements(record: dict[str, typing.Any]) -> bool:
    """Remove nested DOM elements from a `$web_vitals` event so that orjson can dump it.

    For a while, these events included nested DOM structures. They no longer do, but old events can
    still be in the database. This is a `RecursionLimitHandler`.
    """
    if record.get("event", None) != "$web_vitals":
        return False

    try:
        del record["properties"]["$web_vitals_INP_event"]["attribution"]["interactionTargetElement"]
    except KeyError:
        LOGGER.exception("PostHog $web_vitals event didn't match expected structure")
        return False

    return True
