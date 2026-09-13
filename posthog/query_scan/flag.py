"""The `query-scan-warnings` flag: whether a team gets slow query advice, and the thresholds to use."""

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING

import structlog
import posthoganalytics

from posthog.schema import QueryScanMode

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

if TYPE_CHECKING:
    from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)

FLAG_KEY = "query-scan-warnings"

DEFAULT_FLOOR_MS = 1000
DEFAULT_EVENT_RATIO = 0.10
DEFAULT_PERSONS_RATIO = 0.5

_MODES = {mode.value for mode in QueryScanMode}


@frozen
class QueryScanFlag:
    """The flag's variant for a team, and the thresholds from its payload."""

    # `log_only` analyzes but shows nothing; `show` lets clients show findings.
    mode: QueryScanMode
    # A finished run is analyzed only when its ClickHouse time reaches this. A run ClickHouse
    # stopped is analyzed at any duration.
    floor_ms: int
    # No event filter is reported unless the query read at least this share of its date range's events.
    event_ratio: float
    # A persons join is reported only when the persons read is at least this fraction of the events read.
    persons_ratio: float

    @property
    def thresholds_fingerprint(self) -> str:
        """Names the gates an analysis ran under, so one stored under other gates is not served."""
        return f"{self.event_ratio!r}:{self.persons_ratio!r}"


class InvalidPayload(ValueError):
    pass


def get_query_scan_flag(team: Team) -> QueryScanFlag | None:
    """The flag for `team`, or None when off. Evaluated locally on the organization and the project.

    Nothing here raises: the runner calls this on every query, so a flag outage or a bad payload
    reads as off.
    """
    try:
        result = posthoganalytics.get_feature_flag_result(
            FLAG_KEY,
            str(team.uuid),
            groups={"organization": str(team.organization_id), "project": str(team.id)},
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {
                    "id": str(team.id),
                    "created_at": team.created_at.isoformat() if team.created_at else None,
                    "uuid": team.uuid,
                },
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
        if result is None or result.variant not in _MODES:
            return None
        return _parse(QueryScanMode(result.variant), result.payload)
    except InvalidPayload as error:
        # The thresholds are typed by hand into the flag, which only checks that they are JSON. A
        # value the code cannot use turns the feature off and is reported, so the person who set
        # it hears about it.
        capture_exception(error, {"flag": FLAG_KEY, "team_id": team.id})
        logger.exception("query_scan_flag_payload_invalid", team_id=team.id, error=str(error))
        return None
    except Exception:
        logger.warning("query_scan_flag_evaluation_failed", team_id=team.id, exc_info=True)
        return None


def _parse(mode: QueryScanMode, payload: object) -> QueryScanFlag:
    """A missing threshold falls back to its default; one that is present but not a finite number is an error."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError as error:
            raise InvalidPayload("payload is not JSON") from error
    if payload is None:
        values: dict[str, object] = {}
    elif isinstance(payload, dict):
        values = payload
    else:
        raise InvalidPayload(f"payload must be an object, got {payload!r}")
    return QueryScanFlag(
        mode=mode,
        floor_ms=int(_number(values, "floor_ms", DEFAULT_FLOOR_MS)),
        event_ratio=_number(values, "event_ratio", DEFAULT_EVENT_RATIO),
        persons_ratio=_number(values, "persons_ratio", DEFAULT_PERSONS_RATIO),
    )


def _number(values: dict[str, object], key: str, default: float) -> float:
    value = values.get(key, default)
    # bool is an int in Python, and true/false is a typo here, not a threshold.
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise InvalidPayload(f"{key} must be a finite number, got {value!r}")
    return value
