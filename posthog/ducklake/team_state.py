"""Readers for per-team managed-warehouse (duckling) state.

Per-team state lives in the duckgres control-plane org-teams API (read via
:mod:`posthog.ducklake.cp_teams`). This module is the single read seam for that
state: every consumer calls an accessor here instead of talking to the control
plane directly, so the failure posture of each read stays in one place.

Failure posture is per accessor (see each function): backfill-critical reads
raise :class:`CPUnavailableError`, sensor enumerations degrade to empty, status
reads degrade to not-onboarded, and the team-deletion guard fails closed.
"""

from __future__ import annotations

from datetime import date

import structlog

from posthog.ducklake import cp_teams
from posthog.ducklake.common import _get_org_id_for_team, validate_duckgres_identifier

logger = structlog.get_logger(__name__)


class CPUnavailableError(RuntimeError):
    """The duckgres control plane could not answer a team-state read."""


def _get_cp_row(team_id: int) -> cp_teams.CPTeam | None:
    """The team's control-plane row, or None when absent.

    Raises :class:`CPUnavailableError` when the control plane can't answer and the
    cache is cold — callers pick their own degrade posture around it.
    """
    organization_id = _get_org_id_for_team(team_id)
    teams = cp_teams.list_org_teams(organization_id)
    if teams is None:
        raise CPUnavailableError(f"duckgres control plane unreachable reading team state for team {team_id}")
    return next((team for team in teams if team.team_id == team_id), None)


# --- events/persons table names (Dagster duckling backfill) -----------------------


def resolve_events_persons_tables(team_id: int) -> tuple[str, str]:
    """The per-team (events, persons) duckling table names the backfill writes to.

    Failure posture: raises :class:`CPUnavailableError` when the control plane can't
    answer and the cache is cold — the backfill run fails and retries rather than
    writing to guessed tables.
    """
    row = _get_cp_row(team_id)
    if row is None:
        # Legacy single-team ducklings without a team row share the base tables.
        return "events", "persons"
    events_table, persons_table = row.resolved_events_table, row.resolved_persons_table
    validate_duckgres_identifier(events_table)
    validate_duckgres_identifier(persons_table)
    return events_table, persons_table


# --- data-imports schema (v3 sink hot path) ---------------------------------------


def data_imports_schema(team_id: int) -> str:
    """The duckgres schema the v3 data-import sink writes a team into.

    Hot path: reads are served from the cp_teams TTL cache. Failure posture: raises
    :class:`CPUnavailableError` when the control plane can't answer and the cache is
    cold — the batch fails and retries.
    """
    row = _get_cp_row(team_id)
    if row is None:
        # Teams without a control-plane row keep the historical per-team schema.
        return f"posthog_data_imports_team_{team_id}"
    schema = row.resolved_data_imports_schema
    validate_duckgres_identifier(schema)
    return schema


# --- backfill state (warehouse-status UI) -----------------------------------------


def cp_table_suffix(row: cp_teams.CPTeam) -> str | None:
    """Map a CP row onto the historical ``table_suffix`` semantics.

    A grandfathered legacy-shared team pins the base ``events``/``persons`` tables and
    has no suffix (None); every other row's schema name doubles as its suffix (the
    onboarding write stores the same identifier in both places).
    """
    if row.events_table_name == "events" or row.persons_table_name == "persons":
        return None
    return row.schema_name


def team_backfill_row(team_id: int) -> cp_teams.CPTeam | None:
    """The team's control-plane row for status reads, or None when absent.

    Failure posture: a status read must never 500 — an unreachable control plane
    degrades to None (reported as not onboarded / not configured).
    """
    try:
        return _get_cp_row(team_id)
    except CPUnavailableError:
        logger.warning("duckgres_team_state_cp_unavailable", call_site="team_backfill_row", team_id=team_id)
        return None


def team_backfill_state(team_id: int) -> dict[str, object]:
    """The team's duckling backfill state for the warehouse-status UI.

    Failure posture: a status read must never 500 — an unreachable control plane
    degrades to the not-onboarded shape.
    """
    row = team_backfill_row(team_id)
    if row is None:
        return {"has_backfill": False, "table_suffix": None}
    return {"has_backfill": True, "table_suffix": cp_table_suffix(row)}


# --- membership existence (team-deletion guard) -----------------------------------


def backfill_row_exists(team_id: int, organization_id: str) -> bool:
    """Whether the team has a managed-warehouse membership row.

    Failure posture: fail closed — an unreachable control plane reports the row as
    existing, so a possibly-onboarded team's deletion is blocked with a retry error
    instead of silently orphaning its duckgres state.
    """
    teams = cp_teams.list_org_teams(str(organization_id))
    if teams is None:
        logger.warning("duckgres_team_state_cp_unavailable", call_site="backfill_row_exists", team_id=team_id)
        return True
    return any(team.team_id == team_id for team in teams)


# --- enabled-backfill enumeration (Dagster sensors) -------------------------------


class CPBackfillRow:
    """Lightweight sensor row carrying the per-team attributes the duckling sensors touch.

    ``server`` returns self so ``row.server.organization_id`` keeps working where callers
    historically reached the org through a server FK. No ``save()`` on purpose: the
    earliest-event-date write goes through the control plane only.
    """

    def __init__(self, team_id: int, organization_id: str, earliest_event_date: date | None) -> None:
        self.team_id = team_id
        self.organization_id = organization_id
        self.earliest_event_date = earliest_event_date

    @property
    def server(self) -> CPBackfillRow:
        return self


def list_enabled_backfill_rows(call_site: str) -> list[CPBackfillRow]:
    """Every team with warehouse backfills enabled, for sensor enumeration.

    Failure posture: an unreachable control plane yields an empty enumeration (the
    sensor tick becomes a no-op and the next tick retries) — it must never raise.
    """
    cp_rows = cp_teams.list_enabled_backfills()
    if cp_rows is None:
        logger.warning("duckgres_team_state_cp_unavailable", call_site=call_site)
        return []
    return [
        CPBackfillRow(row.team_id, row.organization_id, row.earliest_event_date)
        for row in sorted(cp_rows, key=lambda row: row.team_id)
    ]
