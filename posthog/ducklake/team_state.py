"""Mode-routable readers for per-team managed-warehouse (duckling) state.

Per-team state lives in the Django ``DuckgresServerTeam`` rows and is dual-written
to the duckgres control-plane org-teams API. This module is the single read seam
for that state: every consumer calls an accessor here, and the accessor branches on
the ``DUCKGRES_TEAM_STATE_SOURCE`` setting:

* ``django`` (default): the current queryset logic, unchanged.
* ``cp``: the control-plane rows (via :mod:`posthog.ducklake.cp_teams`).
* ``dual``: serve django, also read the CP, compare field-by-field, and emit
  parity telemetry — the rollout gate before flipping to ``cp``.

Failure posture is per accessor (see each function); parity telemetry is
best-effort and never affects the served value.
"""

from __future__ import annotations

import time
import threading
from datetime import date
from typing import TYPE_CHECKING

import structlog

from posthog.ducklake import cp_teams
from posthog.ducklake.common import _get_org_id_for_team, validate_duckgres_identifier

if TYPE_CHECKING:
    from posthog.ducklake.models import DuckgresServerTeam

logger = structlog.get_logger(__name__)

SOURCE_DJANGO = "django"
SOURCE_DUAL = "dual"
SOURCE_CP = "cp"
_VALID_SOURCES = (SOURCE_DJANGO, SOURCE_DUAL, SOURCE_CP)

# statshog counters emitted by dual-mode parity checks.
PARITY_CHECKS_COUNTER = "duckgres_team_state_parity_checks_total"
PARITY_MISMATCH_COUNTER = "duckgres_team_state_parity_mismatch_total"
PARITY_CP_UNAVAILABLE_COUNTER = "duckgres_team_state_parity_cp_unavailable_total"


class CPUnavailableError(RuntimeError):
    """The duckgres control plane could not answer a team-state read."""


def get_team_state_source() -> str:
    """Resolve the configured read source, defaulting to django on anything unexpected."""
    try:
        from django.conf import settings  # noqa: PLC0415 — keeps this module importable without Django configured

        source = getattr(settings, "DUCKGRES_TEAM_STATE_SOURCE", SOURCE_DJANGO)
    except Exception:
        return SOURCE_DJANGO
    if source not in _VALID_SOURCES:
        logger.warning("duckgres_team_state_source_invalid", source=source)
        return SOURCE_DJANGO
    return source


# --- Parity telemetry (dual mode) -------------------------------------------------

_parity_log_lock = threading.Lock()
_last_mismatch_log: dict[tuple[int, str], float] = {}


def clear_parity_state() -> None:
    """Reset the mismatch-log rate limiter (for tests)."""
    with _parity_log_lock:
        _last_mismatch_log.clear()


def _incr(metric: str, call_site: str) -> None:
    try:
        from statshog.defaults.django import (
            statsd,  # noqa: PLC0415 — statsd needs Django settings; keep it off the import path
        )

        statsd.incr(metric, tags={"call_site": call_site})
    except Exception:
        logger.exception("duckgres_team_state_parity_counter_failed", metric=metric)


def _report_mismatch(call_site: str, team_id: int, field: str, django_value: object, cp_value: object) -> None:
    _incr(PARITY_MISMATCH_COUNTER, call_site)
    now = time.monotonic()
    key = (team_id, field)
    with _parity_log_lock:
        last = _last_mismatch_log.get(key)
        if last is not None and now - last < cp_teams.CACHE_TTL_SECONDS:
            return
        _last_mismatch_log[key] = now
    logger.warning(
        "duckgres_team_state_parity_mismatch",
        team_id=team_id,
        field=field,
        django_value=django_value,
        cp_value=cp_value,
        call_site=call_site,
    )


def _report_cp_unavailable(call_site: str) -> None:
    _incr(PARITY_CP_UNAVAILABLE_COUNTER, call_site)


def _compare(call_site: str, team_id: int, fields: dict[str, tuple[object, object]]) -> None:
    """Count one parity check and report every differing field. Never raises."""
    try:
        _incr(PARITY_CHECKS_COUNTER, call_site)
        for field, (django_value, cp_value) in fields.items():
            if django_value != cp_value:
                _report_mismatch(call_site, team_id, field, django_value, cp_value)
    except Exception:
        logger.exception("duckgres_team_state_parity_compare_failed", call_site=call_site)


# --- events/persons table names (Dagster duckling backfill) -----------------------


def _django_events_persons_tables(team_id: int) -> tuple[str, str]:
    from posthog.ducklake.models import DuckgresServerTeam  # noqa: PLC0415 — keeps Django models off the import path

    suffix = DuckgresServerTeam.objects.filter(team_id=team_id).values_list("table_suffix", flat=True).first()
    if not suffix:
        return "events", "persons"
    validate_duckgres_identifier(suffix)
    return f"events_{suffix}", f"persons_{suffix}"


def _cp_events_persons_tables(team_id: int) -> tuple[str, str]:
    organization_id = _get_org_id_for_team(team_id)
    teams = cp_teams.list_org_teams(organization_id)
    if teams is None:
        raise CPUnavailableError(f"duckgres control plane unreachable resolving table names for team {team_id}")
    row = next((team for team in teams if team.team_id == team_id), None)
    if row is None:
        # Mirrors the django no-row case: legacy single-team ducklings share the base tables.
        return "events", "persons"
    events_table, persons_table = row.resolved_events_table, row.resolved_persons_table
    validate_duckgres_identifier(events_table)
    validate_duckgres_identifier(persons_table)
    return events_table, persons_table


def resolve_events_persons_tables(team_id: int) -> tuple[str, str]:
    """The per-team (events, persons) duckling table names the backfill writes to.

    cp-mode failure posture: raises :class:`CPUnavailableError` when the control plane
    can't answer and the cache is cold — the backfill run fails and retries rather than
    writing to guessed tables.
    """
    source = get_team_state_source()
    if source == SOURCE_CP:
        return _cp_events_persons_tables(team_id)
    django_value = _django_events_persons_tables(team_id)
    if source == SOURCE_DUAL:
        try:
            cp_value = _cp_events_persons_tables(team_id)
        except CPUnavailableError:
            _report_cp_unavailable("resolve_table_names")
        except Exception:
            logger.exception("duckgres_team_state_dual_read_failed", call_site="resolve_table_names")
        else:
            _compare(
                "resolve_table_names",
                team_id,
                {
                    "events_table": (django_value[0], cp_value[0]),
                    "persons_table": (django_value[1], cp_value[1]),
                },
            )
    return django_value


# --- data-imports schema (v3 sink hot path) ---------------------------------------


def _django_data_imports_schema(team_id: int) -> str:
    from posthog.ducklake.models import DuckgresServerTeam  # noqa: PLC0415 — keeps Django models off the import path

    suffix = DuckgresServerTeam.objects.filter(team_id=team_id).values_list("table_suffix", flat=True).first()
    if not suffix:
        return f"posthog_data_imports_team_{team_id}"
    validate_duckgres_identifier(suffix)
    return f"posthog_data_imports_{suffix}"


def _cp_data_imports_schema(team_id: int) -> str:
    organization_id = _get_org_id_for_team(team_id)
    teams = cp_teams.list_org_teams(organization_id)
    if teams is None:
        raise CPUnavailableError(f"duckgres control plane unreachable resolving data-imports schema for team {team_id}")
    row = next((team for team in teams if team.team_id == team_id), None)
    if row is None:
        # Mirrors the django no-row case: the historical per-team schema.
        return f"posthog_data_imports_team_{team_id}"
    schema = row.resolved_data_imports_schema
    validate_duckgres_identifier(schema)
    return schema


def data_imports_schema(team_id: int) -> str:
    """The duckgres schema the v3 data-import sink writes a team into.

    Hot path: cp/dual reads are served from the cp_teams TTL cache. cp-mode failure
    posture: raises :class:`CPUnavailableError` when the control plane can't answer and
    the cache is cold — the batch fails and retries.
    """
    source = get_team_state_source()
    if source == SOURCE_CP:
        return _cp_data_imports_schema(team_id)
    django_value = _django_data_imports_schema(team_id)
    if source == SOURCE_DUAL:
        try:
            cp_value = _cp_data_imports_schema(team_id)
        except CPUnavailableError:
            _report_cp_unavailable("data_imports_schema")
        except Exception:
            logger.exception("duckgres_team_state_dual_read_failed", call_site="data_imports_schema")
        else:
            _compare("data_imports_schema", team_id, {"data_imports_schema": (django_value, cp_value)})
    return django_value


# --- backfill state (warehouse-status UI) -----------------------------------------


def _django_team_backfill_state(team_id: int) -> dict[str, object]:
    from posthog.ducklake.models import DuckgresServerTeam  # noqa: PLC0415 — keeps Django models off the import path

    backfill = DuckgresServerTeam.objects.filter(team_id=team_id).values("table_suffix").first()
    if backfill is None:
        return {"has_backfill": False, "table_suffix": None}
    return {"has_backfill": True, "table_suffix": backfill["table_suffix"]}


def _cp_table_suffix(row: cp_teams.CPTeam) -> str | None:
    """Reverse-map a CP row onto the Django ``table_suffix`` semantics.

    A grandfathered legacy-shared team pins the base ``events``/``persons`` tables and
    has no suffix (None); every other row's schema name doubles as its suffix (the
    dual-write stores the same identifier in both places).
    """
    if row.events_table_name == "events" or row.persons_table_name == "persons":
        return None
    return row.schema_name


def _cp_team_backfill_state(team_id: int) -> dict[str, object]:
    organization_id = _get_org_id_for_team(team_id)
    teams = cp_teams.list_org_teams(organization_id)
    if teams is None:
        raise CPUnavailableError(f"duckgres control plane unreachable reading backfill state for team {team_id}")
    row = next((team for team in teams if team.team_id == team_id), None)
    if row is None:
        return {"has_backfill": False, "table_suffix": None}
    return {"has_backfill": True, "table_suffix": _cp_table_suffix(row)}


def team_backfill_state(team_id: int) -> dict[str, object]:
    """The team's duckling backfill state for the warehouse-status UI.

    cp-mode failure posture: a status read must never 500 — an unreachable control
    plane degrades to the not-onboarded shape (mirroring the existing best-effort
    control-plane reads in the status path).
    """
    source = get_team_state_source()
    if source == SOURCE_CP:
        try:
            return _cp_team_backfill_state(team_id)
        except CPUnavailableError:
            logger.warning("duckgres_team_state_cp_unavailable", call_site="team_backfill_state", team_id=team_id)
            return {"has_backfill": False, "table_suffix": None}
    django_value = _django_team_backfill_state(team_id)
    if source == SOURCE_DUAL:
        try:
            cp_value = _cp_team_backfill_state(team_id)
        except CPUnavailableError:
            _report_cp_unavailable("team_backfill_state")
        except Exception:
            logger.exception("duckgres_team_state_dual_read_failed", call_site="team_backfill_state")
        else:
            _compare(
                "team_backfill_state",
                team_id,
                {
                    "has_backfill": (django_value["has_backfill"], cp_value["has_backfill"]),
                    "table_suffix": (django_value["table_suffix"], cp_value["table_suffix"]),
                },
            )
    return django_value


# --- membership existence (team-deletion guard) -----------------------------------


def backfill_row_exists(team_id: int, organization_id: str) -> bool:
    """Whether the team has a managed-warehouse membership row.

    cp-mode failure posture: fail closed — an unreachable control plane reports the
    row as existing, so a possibly-onboarded team's deletion is blocked with a retry
    error instead of silently orphaning its duckgres state.
    """
    source = get_team_state_source()
    if source == SOURCE_CP:
        teams = cp_teams.list_org_teams(str(organization_id))
        if teams is None:
            logger.warning("duckgres_team_state_cp_unavailable", call_site="backfill_row_exists", team_id=team_id)
            return True
        return any(team.team_id == team_id for team in teams)

    from posthog.ducklake.models import DuckgresServerTeam  # noqa: PLC0415 — keeps Django models off the import path

    django_value = DuckgresServerTeam.objects.filter(team_id=team_id).exists()
    if source == SOURCE_DUAL:
        teams = cp_teams.list_org_teams(str(organization_id))
        if teams is None:
            _report_cp_unavailable("backfill_row_exists")
        else:
            cp_value = any(team.team_id == team_id for team in teams)
            _compare("backfill_row_exists", team_id, {"row_exists": (django_value, cp_value)})
    return django_value


# --- enabled-backfill enumeration (Dagster sensors) -------------------------------


class CPBackfillRow:
    """Lightweight sensor row mirroring the ``DuckgresServerTeam`` attributes sensors touch.

    ``server`` returns self so ``row.server.organization_id`` keeps working where the
    django rows expose the org through their server FK. No ``save()`` on purpose: in cp
    mode the earliest-event-date write goes through the control plane only.
    """

    def __init__(self, team_id: int, organization_id: str, earliest_event_date: date | None) -> None:
        self.team_id = team_id
        self.organization_id = organization_id
        self.earliest_event_date = earliest_event_date

    @property
    def server(self) -> CPBackfillRow:
        return self


def _django_enabled_backfills() -> list[DuckgresServerTeam]:
    from posthog.ducklake.models import DuckgresServerTeam  # noqa: PLC0415 — keeps Django models off the import path

    return list(DuckgresServerTeam.objects.filter(backfill_enabled=True).select_related("server").order_by("team_id"))


def list_enabled_backfill_rows(call_site: str) -> list[DuckgresServerTeam | CPBackfillRow]:
    """Every team with warehouse backfills enabled, for sensor enumeration.

    cp-mode failure posture: an unreachable control plane yields an empty enumeration
    (the sensor tick becomes a no-op and the next tick retries) — it must never raise.
    """
    source = get_team_state_source()
    if source == SOURCE_CP:
        cp_rows = cp_teams.list_enabled_backfills()
        if cp_rows is None:
            logger.warning("duckgres_team_state_cp_unavailable", call_site=call_site)
            return []
        return [
            CPBackfillRow(row.team_id, row.organization_id, row.earliest_event_date)
            for row in sorted(cp_rows, key=lambda row: row.team_id)
        ]
    django_rows = _django_enabled_backfills()
    if source == SOURCE_DUAL:
        _compare_enabled_backfills(call_site, django_rows)
    return list(django_rows)


def _compare_enabled_backfills(call_site: str, django_rows: list[DuckgresServerTeam]) -> None:
    """Dual-mode parity for the sensor enumeration: membership + earliest_event_date."""
    try:
        cp_rows = cp_teams.list_enabled_backfills()
        if cp_rows is None:
            _report_cp_unavailable(call_site)
            return
        _incr(PARITY_CHECKS_COUNTER, call_site)
        cp_by_team = {row.team_id: row for row in cp_rows}
        django_team_ids = set()
        for django_row in django_rows:
            django_team_ids.add(django_row.team_id)
            cp_row = cp_by_team.get(django_row.team_id)
            if cp_row is None:
                _report_mismatch(call_site, django_row.team_id, "backfill_enabled", True, False)
                continue
            if django_row.earliest_event_date != cp_row.earliest_event_date:
                _report_mismatch(
                    call_site,
                    django_row.team_id,
                    "earliest_event_date",
                    django_row.earliest_event_date,
                    cp_row.earliest_event_date,
                )
        for team_id in cp_by_team.keys() - django_team_ids:
            _report_mismatch(call_site, team_id, "backfill_enabled", False, True)
    except Exception:
        logger.exception("duckgres_team_state_parity_compare_failed", call_site=call_site)
