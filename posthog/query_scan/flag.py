"""The `query-scan-warnings` flag: whether a team gets slow query advice, and the thresholds to use."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal, cast

import structlog
import posthoganalytics

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)

FLAG_KEY = "query-scan-warnings"

DEFAULT_FLOOR_MS = 1000
DEFAULT_EVENT_RATIO = 0.10
DEFAULT_PERSONS_RATIO = 0.5

QueryScanMode = Literal["log_only", "show"]
MODES: tuple[QueryScanMode, ...] = ("log_only", "show")


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


def get_query_scan_flag(team: Team) -> QueryScanFlag | None:
    """The flag for `team`, or None when off. Evaluated locally on the project; a flag outage reads as off."""
    try:
        result = posthoganalytics.get_feature_flag_result(
            FLAG_KEY,
            str(team.uuid),
            groups={"project": str(team.id)},
            group_properties={
                "project": {
                    "id": str(team.id),
                    "created_at": team.created_at.isoformat() if team.created_at else None,
                    "uuid": team.uuid,
                }
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning("query_scan_flag_evaluation_failed", team_id=team.id, exc_info=True)
        return None
    if result is None or result.variant not in MODES:
        return None
    return _parse(cast("QueryScanMode", result.variant), result.payload)


def _parse(mode: QueryScanMode, payload: object) -> QueryScanFlag:
    """The thresholds are typed by hand into the payload, so each field falls back on its own."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = {}
    values = payload if isinstance(payload, dict) else {}
    return QueryScanFlag(
        mode=mode,
        floor_ms=_as_int(values.get("floor_ms"), DEFAULT_FLOOR_MS),
        event_ratio=_as_float(values.get("event_ratio"), DEFAULT_EVENT_RATIO),
        persons_ratio=_as_float(values.get("persons_ratio"), DEFAULT_PERSONS_RATIO),
    )


def _as_int(value: object, default: int) -> int:
    # bool is an int in Python, and true/false is a typo here, not a threshold.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return int(value)


def _as_float(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return float(value)
