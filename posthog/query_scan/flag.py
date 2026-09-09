"""The feature flag that turns query scan warnings on for a team, and the thresholds it carries."""

from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING, Literal, cast

import structlog
import posthoganalytics
from cachetools import TTLCache

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)

FLAG_KEY = "query-scan-warnings"
CACHE_TTL_SECONDS = 60
CACHE_MAX_TEAMS = 10_000

DEFAULT_FLOOR_MS = 1000
DEFAULT_EVENT_RATIO = 0.10
DEFAULT_PERSONS_RATIO = 0.5

QueryScanMode = Literal["log_only", "show"]
MODES: tuple[QueryScanMode, ...] = ("log_only", "show")


@frozen
class QueryScanFlag:
    """What the flag says for one team: how much clients may show, and the thresholds to analyze at."""

    mode: QueryScanMode
    floor_ms: int
    event_ratio: float
    persons_ratio: float


_flag_cache: TTLCache[int, QueryScanFlag | None] = TTLCache(maxsize=CACHE_MAX_TEAMS, ttl=CACHE_TTL_SECONDS)
# cachetools caches are not thread-safe; the lock guards threaded WSGI/Celery workers.
_flag_cache_lock = threading.Lock()


def get_query_scan_flag(team: Team) -> QueryScanFlag | None:
    """The flag for `team`, or None when query scan warnings are off for it.

    Every blocking query asks, so the answer is held in-process for a minute. Off is cached too,
    which is what keeps an unflagged team off the flag evaluation path.
    """
    with _flag_cache_lock:
        try:
            return _flag_cache[team.id]
        except KeyError:
            pass

    flag = _evaluate(team)

    with _flag_cache_lock:
        _flag_cache[team.id] = flag
    return flag


def _evaluate(team: Team) -> QueryScanFlag | None:
    """Read the variant and its payload from the flag in one call. Never raises: any failure reads as off.

    Local evaluation sees only the properties passed here, so the flag's conditions must be on the
    project id.
    """
    try:
        distinct_id = str(team.uuid)
        groups = {"project": str(team.id)}
        group_properties = {
            "project": {
                "id": str(team.id),
                "created_at": team.created_at.isoformat() if team.created_at else None,
                "uuid": team.uuid,
            }
        }
        result = posthoganalytics.get_feature_flag_result(
            FLAG_KEY,
            distinct_id,
            groups=groups,
            group_properties=group_properties,
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
        if result is None or result.variant not in MODES:
            return None
        mode = cast("QueryScanMode", result.variant)
        return _flag_from_payload(mode, result.payload)
    except Exception:
        logger.warning("query_scan_flag_evaluation_failed", team_id=team.id, exc_info=True)
        return None


def _flag_from_payload(mode: QueryScanMode, payload: object) -> QueryScanFlag:
    """Thresholds live in the payload so they can move without a deploy, which means the code has to
    survive a payload somebody typed by hand: a missing or malformed value takes the default."""
    values = _payload_values(payload)
    return QueryScanFlag(
        mode=mode,
        floor_ms=_as_int(values.get("floor_ms"), DEFAULT_FLOOR_MS),
        event_ratio=_as_float(values.get("event_ratio"), DEFAULT_EVENT_RATIO),
        persons_ratio=_as_float(values.get("persons_ratio"), DEFAULT_PERSONS_RATIO),
    )


def _payload_values(payload: object) -> dict[str, object]:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return {}
    return payload if isinstance(payload, dict) else {}


def _as_int(value: object, default: int) -> int:
    # bool is an int in Python, and a true/false threshold is a typo rather than a number.
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return default


def _as_float(value: object, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    return default
