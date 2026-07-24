"""Read-side client for the duckgres control-plane org-teams API.

The control plane is becoming the source of truth for per-team managed-warehouse
state (today mirrored from the Django ``DuckgresServerTeam`` rows via dual-writes).
This module exposes the CP rows as :class:`CPTeam` values plus a small process-local
TTL cache so hot paths (the v3 data-import sink schema resolution) don't issue one
HTTP call per batch.

Legacy-name semantics of a CP row: a non-NULL ``events_table_name`` /
``persons_table_name`` / ``schema_data_imports_name`` is a grandfathered explicit
pin; NULL means "derive from ``schema_name``". The derive rule here is the
TRANSITIONAL one — writers still produce the old suffix-derived layout, so for
every existing row it is byte-identical to the Django-side derivation:

* events: ``events_<schema_name>``
* persons: ``persons_<schema_name>``
* data-imports schema: ``posthog_data_imports_<schema_name>``

Do NOT change this to the future ``<schema_name>.events`` layout until the writers do.

Every fetcher returns ``None`` when the control plane is unreachable or answers
unusably — callers decide the failure posture (fail open, fail closed, or raise).
"""

from __future__ import annotations

import time
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

logger = logging.getLogger(__name__)

# TTL for the process-local cache below. Monkeypatchable in tests; sized so sensor
# ticks and per-batch schema resolutions coalesce onto one CP call per minute.
CACHE_TTL_SECONDS: float = 60.0


@dataclass
class CPTeam:
    """One duckgres control-plane org-team row."""

    team_id: int
    organization_id: str
    schema_name: str
    enabled: bool
    backfill_enabled: bool
    events_table_name: str | None
    persons_table_name: str | None
    schema_data_imports_name: str | None
    earliest_event_date: date | None

    @property
    def resolved_events_table(self) -> str:
        """Events table name: the grandfathered pin, else the transitional derivation."""
        return self.events_table_name or f"events_{self.schema_name}"

    @property
    def resolved_persons_table(self) -> str:
        """Persons table name: the grandfathered pin, else the transitional derivation."""
        return self.persons_table_name or f"persons_{self.schema_name}"

    @property
    def resolved_data_imports_schema(self) -> str:
        """Data-imports schema: the grandfathered pin, else the transitional derivation."""
        return self.schema_data_imports_name or f"posthog_data_imports_{self.schema_name}"


def _parse_earliest_event_date(raw: object) -> date | None:
    if not raw:
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        logger.warning("cp_teams_unparseable_earliest_event_date: %r", raw)
        return None


def team_from_row(row: dict, *, organization_id: str | None = None) -> CPTeam | None:
    """Build a CPTeam from a raw API row, or None when the row is unusable."""
    try:
        team_id = int(row["team_id"])  # defensive: the API serializes ints, but coerce anyway
    except (KeyError, TypeError, ValueError):
        logger.warning("cp_teams_row_missing_team_id")
        return None
    schema_name = row.get("schema_name")
    if not isinstance(schema_name, str) or not schema_name:
        logger.warning("cp_teams_row_missing_schema_name (team_id=%s)", team_id)
        return None
    # Writes derive their URL from the org id, so a row without one is unusable — an
    # empty org would send updates down /orgs//teams/... and fail silently every tick.
    org = row.get("org_id") or organization_id
    if not org:
        logger.warning("cp_teams_row_missing_org_id (team_id=%s)", team_id)
        return None
    return CPTeam(
        team_id=team_id,
        organization_id=str(org),
        schema_name=schema_name,
        enabled=bool(row.get("enabled")),
        backfill_enabled=bool(row.get("backfill_enabled")),
        events_table_name=row.get("events_table_name") or None,
        persons_table_name=row.get("persons_table_name") or None,
        schema_data_imports_name=row.get("schema_data_imports_name") or None,
        earliest_event_date=_parse_earliest_event_date(row.get("earliest_event_date")),
    )


_cache_lock = threading.Lock()
_cache: dict[tuple[str, ...], tuple[float, list[dict]]] = {}


def clear_cache() -> None:
    """Drop every cached CP response (for tests and operational cache busts)."""
    with _cache_lock:
        _cache.clear()


def _cached_rows(key: tuple[str, ...], fetch: Callable[[], list[dict] | None]) -> list[dict] | None:
    """Serve `key` from the TTL cache, fetching (and caching only successes) on a miss."""
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    rows = fetch()
    if rows is not None:
        with _cache_lock:
            _cache[key] = (time.monotonic(), rows)
    return rows


def _fetch_org_rows(organization_id: str) -> list[dict] | None:
    # Deferred: keeps the DRF-importing adapter (and the products presentation stack)
    # off this module's import path.
    from products.data_warehouse.backend.presentation.views import managed_warehouse  # noqa: PLC0415

    try:
        resp = managed_warehouse.list_teams(organization_id, require_enabled=False)
        return managed_warehouse._teams_from_response(resp)
    except Exception:
        logger.exception("cp_teams_list_org_teams_failed (organization_id=%s)", organization_id)
        return None


def _fetch_all_rows() -> list[dict] | None:
    # Deferred for the same reason as _fetch_org_rows.
    from products.data_warehouse.backend.presentation.views import managed_warehouse  # noqa: PLC0415

    try:
        resp = managed_warehouse.list_all_teams()
        return managed_warehouse._teams_from_response(resp)
    except Exception:
        logger.exception("cp_teams_list_all_teams_failed")
        return None


def list_org_teams(organization_id: str) -> list[CPTeam] | None:
    """All CP team rows of an org, or None when the control plane can't answer."""
    org_id = str(organization_id)
    rows = _cached_rows(("org_teams", org_id), lambda: _fetch_org_rows(org_id))
    if rows is None:
        return None
    teams = (team_from_row(row, organization_id=org_id) for row in rows)
    return [team for team in teams if team is not None]


def get_team(organization_id: str, team_id: int) -> CPTeam | None:
    """The CP row for one team, or None when absent OR the control plane can't answer.

    Callers that must distinguish "absent" from "unreachable" should use
    :func:`list_org_teams` directly.
    """
    teams = list_org_teams(organization_id)
    if teams is None:
        return None
    wanted = int(team_id)
    return next((team for team in teams if team.team_id == wanted), None)


def list_enabled_backfills() -> list[CPTeam] | None:
    """Every CP team row with backfill_enabled, across all orgs, or None when unreachable."""
    rows = _cached_rows(("all_teams",), _fetch_all_rows)
    if rows is None:
        return None
    teams = (team_from_row(row) for row in rows)
    return [team for team in teams if team is not None and team.backfill_enabled]
