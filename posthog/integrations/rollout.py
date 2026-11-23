"""Per-team rollout of the dual write of integrations to the credentials service.

The `integrations-service-dual-write` feature flag selects the teams, and its payload selects the
integration kinds: `{"kinds": ["slack", "github"]}`, or `{"kinds": ["*"]}` for every kind. A team with
the flag off, no payload, a malformed payload or a failed evaluation has no kinds.

Results are cached per process for `CACHE_TTL_SECONDS`, so a change to the flag, or the deletion of a
team, can take that long to show in `dual_write_kinds` and `dual_write_kinds_for_teams`.
"""

import json
import time
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from uuid import UUID

import structlog
import posthoganalytics
from prometheus_client import Counter

from posthog.models.team import Team

logger = structlog.get_logger(__name__)

DUAL_WRITE_FLAG = "integrations-service-dual-write"
ALL_KINDS = "*"
CACHE_TTL_SECONDS = 60.0
MAX_CACHE_ENTRIES = 10_000

NO_KINDS: frozenset[str] = frozenset()

FLAG_ERRORS = Counter(
    "integrations_service_rollout_flag_errors_total",
    "Failed evaluations of the integrations service rollout flag",
)


class TeamGone(Exception):
    def __init__(self, team_id: int) -> None:
        super().__init__(f"Team {team_id} does not exist")
        self.team_id = team_id


@dataclass(frozen=True)
class _TeamIdentity:
    id: int
    uuid: UUID
    organization_id: UUID


class _ExpiringKinds:
    def __init__(
        self,
        ttl_seconds: float = CACHE_TTL_SECONDS,
        max_entries: int = MAX_CACHE_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._entries: dict[int, tuple[float, frozenset[str]]] = {}
        self._lock = threading.Lock()

    def get(self, team_id: int) -> frozenset[str] | None:
        now = self._clock()
        with self._lock:
            entry = self._entries.get(team_id)
            if entry is None:
                return None
            if entry[0] <= now:
                del self._entries[team_id]
                return None
            return entry[1]

    def put(self, team_id: int, kinds: frozenset[str]) -> None:
        expires_at = self._clock() + self._ttl_seconds
        with self._lock:
            self._entries.pop(team_id, None)
            # Entries are in insertion order, so the first entry is the oldest one.
            while self._entries and len(self._entries) >= self._max_entries:
                del self._entries[next(iter(self._entries))]
            self._entries[team_id] = (expires_at, kinds)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_cache = _ExpiringKinds()


def dual_write_kinds(team_id: int) -> frozenset[str]:
    """The integration kinds that the team dual writes. `ALL_KINDS` in the set means every kind.

    A team deleted within the cache TTL can still return its cached kinds. Use `require_team_kinds`
    where that matters.
    """
    cached = _cache.get(team_id)
    if cached is not None:
        return cached
    team = _load_teams([team_id]).get(team_id)
    if team is None:
        return NO_KINDS
    return _evaluate_and_cache(team)


def dual_write_enabled(team_id: int, kind: str) -> bool:
    kinds = dual_write_kinds(team_id)
    return ALL_KINDS in kinds or kind in kinds


def dual_write_kinds_for_teams(team_ids: Iterable[int]) -> dict[int, frozenset[str]]:
    """`dual_write_kinds` for many teams, with one `Team` query for the teams that are not cached.

    A team deleted within the cache TTL can still return its cached kinds, as in `dual_write_kinds`.
    """
    result: dict[int, frozenset[str]] = {}
    missing: list[int] = []
    for team_id in dict.fromkeys(team_ids):
        cached = _cache.get(team_id)
        if cached is None:
            missing.append(team_id)
        else:
            result[team_id] = cached
    if missing:
        teams = _load_teams(missing)
        for team_id in missing:
            team = teams.get(team_id)
            result[team_id] = NO_KINDS if team is None else _evaluate_and_cache(team)
    return result


def require_team_kinds(team_id: int) -> frozenset[str]:
    """Like `dual_write_kinds`, but raises `TeamGone` when the team does not exist.

    The team is always read from the database, also when its kinds are cached, so that a team deleted
    within the cache TTL still raises.
    """
    team = _load_teams([team_id]).get(team_id)
    if team is None:
        raise TeamGone(team_id)
    cached = _cache.get(team_id)
    if cached is not None:
        return cached
    return _evaluate_and_cache(team)


def reset_caches() -> None:
    _cache.clear()


def _load_teams(team_ids: list[int]) -> dict[int, _TeamIdentity]:
    rows = Team.objects.filter(id__in=team_ids).values_list("id", "uuid", "organization_id")
    return {row[0]: _TeamIdentity(id=row[0], uuid=row[1], organization_id=row[2]) for row in rows}


def _evaluate_and_cache(team: _TeamIdentity) -> frozenset[str]:
    try:
        # A disabled SDK (tests, opted-out installs, self-capture) never evaluates flags. That is off,
        # not a failure, so it is cached and not counted.
        if posthoganalytics.setup().disabled:
            _cache.put(team.id, NO_KINDS)
            return NO_KINDS
        result = posthoganalytics.get_feature_flag_result(
            DUAL_WRITE_FLAG,
            str(team.uuid),
            groups={"organization": str(team.organization_id), "project": str(team.id)},
            person_properties={"team_id": str(team.id)},
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team.id)},
            },
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception as error:
        return _evaluation_failed(team, type(error).__name__)
    # The SDK returns None, and does not raise, both when a remote evaluation fails and when the
    # flag does not exist. The loaded local definitions tell the two cases apart.
    if result is None:
        try:
            flag_off_everywhere = _flag_off_everywhere()
        except Exception as error:
            return _evaluation_failed(team, type(error).__name__)
        if not flag_off_everywhere:
            return _evaluation_failed(team, "NoResult")
    # The payload of the flag's `false` result must not enable a team outside the rollout.
    if result is None or not result.enabled:
        _cache.put(team.id, NO_KINDS)
        return NO_KINDS
    payload = result.payload
    kinds = _parse_kinds(payload)
    if kinds is None:
        logger.warning(
            "integrations_service_rollout_payload_malformed",
            team_id=team.id,
            flag=DUAL_WRITE_FLAG,
            payload_type=type(payload).__name__,
        )
        kinds = NO_KINDS
    _cache.put(team.id, kinds)
    return kinds


def _flag_off_everywhere() -> bool:
    """True when the loaded local definitions show the flag as missing, deleted or disabled.

    False when the definitions are not loaded, because then a missing result can also be a failed
    remote evaluation.
    """
    definitions = posthoganalytics.feature_flag_definitions()
    if definitions is None:
        return False
    definition = next((flag for flag in definitions if flag.get("key") == DUAL_WRITE_FLAG), None)
    return definition is None or bool(definition.get("deleted")) or not definition.get("active")


def _evaluation_failed(team: _TeamIdentity, error_type: str) -> frozenset[str]:
    # Not cached, so that one failure does not turn the dual write off for the whole TTL.
    FLAG_ERRORS.inc()
    logger.warning(
        "integrations_service_rollout_flag_failed",
        team_id=team.id,
        flag=DUAL_WRITE_FLAG,
        error_type=error_type,
    )
    return NO_KINDS


def _parse_kinds(payload: object) -> frozenset[str] | None:
    """The kinds in the payload, or None when the payload is malformed."""
    if payload is None:
        return NO_KINDS
    if isinstance(payload, str | bytes):
        try:
            payload = json.loads(payload)
        except (ValueError, RecursionError):
            return None
    if not isinstance(payload, dict):
        return None
    kinds = payload.get("kinds")
    if not isinstance(kinds, list) or not all(isinstance(kind, str) and kind for kind in kinds):
        return None
    if ALL_KINDS in kinds:
        return frozenset({ALL_KINDS})
    return frozenset(kinds)
