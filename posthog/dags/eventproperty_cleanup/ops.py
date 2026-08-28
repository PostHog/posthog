"""Dagster ops and job for the posthog_eventproperty cleanup crawler.

Manual-only: no schedule, no sensor, dry run by default. Five sequential ops in one process: nothing runs
in parallel because the table lives on the shared cloud primary and every unit is resumable by relaunch.
Discovery and scoring read the replica when one is configured; only deletes touch the primary.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime

from django.conf import settings
from django.db import connection, connections
from django.db.backends.base.base import BaseDatabaseWrapper

import dagster
import psycopg2

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.custom_metrics import MetricsClient
from posthog.dags.common import JobOwners
from posthog.dataclasses import frozen

from . import sql
from .config import EventPropertyCleanupConfig
from .dormancy import (
    ClickHouseProbe,
    DormancyVerdict,
    PersonsProbe,
    clickhouse_probe_for,
    dormant_unit,
    evaluate,
    persons_probe_for,
    score_team,
    scorecard_csv,
    still_dormant,
    top_teams,
)
from .engine import DeleteEngine, DjangoPostgresBackend, UnitResult
from .units import WorkUnit, discover_pollution_units, discover_retention_units

REPLICA_ALIAS = "replica"
UNIT_LOG_LIMIT = 200


@frozen
class PreflightReport:
    database: str
    is_primary: bool
    indexes: tuple[str, ...]
    replication_slots: tuple[str, ...]
    backend_waits_visible: bool
    discovery_on_replica: bool
    vacuumed: bool


@frozen
class ModeResult:
    mode: str
    units: int
    teams: int
    estimated_rows: int
    rows_deleted: int
    batches: int
    pauses: int
    vacuums: int
    # Rows deleted after the last VACUUM, so the collect step knows whether one more is due.
    rows_since_vacuum: int
    stopped_units: int
    stopped_reason: str | None


def _region() -> str:
    return str(getattr(settings, "CLOUD_DEPLOYMENT", None) or "local")


def discovery_connection() -> BaseDatabaseWrapper:
    """The replica when Dagster has one configured, else the primary."""
    return connections[REPLICA_ALIAS] if REPLICA_ALIAS in connections.databases else connection


def discovery_cursor(config: EventPropertyCleanupConfig):
    """A cursor on the discovery connection with the discovery statement_timeout applied.

    On the primary the delete transactions override this with `SET LOCAL`, so it only bounds discovery.
    """
    cursor = discovery_connection().cursor()
    cursor.execute("SET statement_timeout = %s", (config.discovery_statement_timeout,))
    return cursor


def _skipped(mode: str) -> ModeResult:
    return ModeResult(
        mode=mode,
        units=0,
        teams=0,
        estimated_rows=0,
        rows_deleted=0,
        batches=0,
        pauses=0,
        vacuums=0,
        rows_since_vacuum=0,
        stopped_units=0,
        stopped_reason="disabled",
    )


@dagster.op
def preflight_op(context: dagster.OpExecutionContext, config: EventPropertyCleanupConfig) -> PreflightReport:
    with connection.cursor() as cursor:
        cursor.execute(sql.PREFLIGHT_PRIMARY)
        in_recovery, database = cursor.fetchone()
        cursor.execute(sql.PREFLIGHT_INDEXES, {"table": sql.TABLE})
        indexes = tuple(sorted(row[0] for row in cursor.fetchall()))
        cursor.execute(sql.PREFLIGHT_REPLICATION_SLOTS)
        slots = tuple(f"{row[0]}(active={row[1]})" for row in cursor.fetchall())
        cursor.execute(sql.PREFLIGHT_ACTIVITY_VISIBILITY)
        backend_waits_visible = bool(cursor.fetchone()[0])

    if config.require_primary and in_recovery:
        raise dagster.Failure(f"{database} is a replica; the cleanup needs the primary")
    missing = [name for name in sql.REQUIRED_INDEXES if name not in indexes]
    if missing:
        raise dagster.Failure(f"required indexes missing on {sql.TABLE}: {missing}")
    if config.require_no_replication_slots and slots:
        raise dagster.Failure(
            f"replication slots exist: {slots}. A logical slot would retain every byte of WAL this job writes."
        )
    if not backend_waits_visible:
        message = (
            "role cannot read other sessions' wait events (needs pg_read_all_stats); "
            "the blocked-propdefs pause signal is disabled"
        )
        if config.require_activity_visibility:
            raise dagster.Failure(message)
        context.log.warning(message)

    discovery_on_replica = REPLICA_ALIAS in connections.databases
    if not discovery_on_replica:
        message = "no replica connection configured; discovery and scoring will read the primary"
        if config.require_discovery_replica:
            raise dagster.Failure(message)
        context.log.warning(message)

    vacuumed = False
    if config.vacuum_on_start and config.vacuum and not config.dry_run:
        with connection.cursor() as cursor:
            cursor.execute(sql.HEALTH_TABLE_STATS)
            row = cursor.fetchone()
        dead_tuples = int(row[1]) if row else 0
        if dead_tuples >= config.vacuum_on_start_min_dead_tuples:
            notices = DjangoPostgresBackend().vacuum(config.vacuum_cost_delay_ms, config.vacuum_cost_limit)
            context.log.info("preflight vacuum (%s dead tuples): %s", f"{dead_tuples:,}", notices[-12:])
            vacuumed = True
        else:
            context.log.info("skipping preflight vacuum: %s dead tuples", f"{dead_tuples:,}")

    report = PreflightReport(
        database=database,
        is_primary=not in_recovery,
        indexes=indexes,
        replication_slots=slots,
        backend_waits_visible=backend_waits_visible,
        discovery_on_replica=discovery_on_replica,
        vacuumed=vacuumed,
    )
    context.add_output_metadata(
        {
            "database": database,
            "is_primary": not in_recovery,
            "indexes": ", ".join(indexes),
            "replication_slots": ", ".join(slots) or "none",
            "backend_waits_visible": backend_waits_visible,
            "discovery_on_replica": discovery_on_replica,
            "dry_run": config.dry_run,
        }
    )
    return report


def run_units(
    context: dagster.OpExecutionContext,
    config: EventPropertyCleanupConfig,
    preflight: PreflightReport,
    mode: str,
    units: Iterator[WorkUnit],
    cluster: ClickhouseCluster,
    revalidator: Callable[[WorkUnit], Callable[[], bool]] | None = None,
) -> ModeResult:
    """Stream units through one engine, deleting as they are discovered. Dry runs only estimate."""
    engine = DeleteEngine(
        config,
        DjangoPostgresBackend(backend_waits_visible=preflight.backend_waits_visible),
        metrics=None if config.dry_run else MetricsClient(cluster),
        metric_labels={"mode": mode, "region": _region()},
    )
    results: list[UnitResult] = []
    teams: set[int] = set()
    estimated = 0
    seen = 0
    stopped_reason: str | None = None
    for unit in units:
        if unit.team_id in config.never_delete_team_ids:
            continue
        seen += 1
        teams.add(unit.team_id)
        estimated += unit.est_rows
        if seen <= UNIT_LOG_LIMIT:
            context.log.info("unit %s ~%s rows (%s)", unit.label, f"{unit.est_rows:,}", unit.reason)
        if config.dry_run:
            continue
        try:
            result = engine.run_unit(unit, revalidator(unit) if revalidator else None)
        except Exception as exc:
            raise dagster.Failure(
                f"{unit.label} failed: {exc}",
                metadata={
                    "mode": mode,
                    "team_id": unit.team_id,
                    "key": str(unit.key),
                    "rows_deleted_so_far": engine.rows_deleted_total,
                },
            ) from exc
        results.append(result)
        if result.stopped_reason in ("max_rows", "max_runtime"):
            stopped_reason = result.stopped_reason
            context.log.warning("stopping %s mode: %s", mode, stopped_reason)
            break

    mode_result = ModeResult(
        mode=mode,
        units=seen,
        teams=len(teams),
        estimated_rows=estimated,
        rows_deleted=sum(r.rows_deleted for r in results),
        batches=sum(r.batches for r in results),
        pauses=sum(r.pauses for r in results),
        vacuums=engine.vacuums,
        rows_since_vacuum=engine.rows_since_vacuum,
        stopped_units=sum(1 for r in results if r.stopped_reason),
        stopped_reason=stopped_reason or ("dry_run" if config.dry_run else None),
    )
    context.add_output_metadata(
        {
            "mode": mode,
            "units": mode_result.units,
            "teams": mode_result.teams,
            "estimated_rows": mode_result.estimated_rows,
            "rows_deleted": mode_result.rows_deleted,
            "batches": mode_result.batches,
            "pauses": mode_result.pauses,
            "vacuums": mode_result.vacuums,
            "stopped_units": mode_result.stopped_units,
            "stopped_reason": mode_result.stopped_reason or "none",
        }
    )
    return mode_result


@dagster.op
def run_pollution_op(
    context: dagster.OpExecutionContext,
    config: EventPropertyCleanupConfig,
    preflight: PreflightReport,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> ModeResult:
    if not config.pollution_enabled:
        context.log.info("pollution mode disabled")
        return _skipped("pollution")
    with discovery_cursor(config) as cursor:
        return run_units(context, config, preflight, "pollution", discover_pollution_units(cursor, config), cluster)


@dagster.op
def run_retention_op(
    context: dagster.OpExecutionContext,
    config: EventPropertyCleanupConfig,
    preflight: PreflightReport,
    previous: ModeResult,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> ModeResult:
    if config.retention_days is None:
        context.log.info("retention mode disabled (retention_days is None)")
        return _skipped("retention")
    with discovery_cursor(config) as cursor:
        return run_units(context, config, preflight, "retention", discover_retention_units(cursor, config), cluster)


def score_dormant_teams(
    cursor,
    config: EventPropertyCleanupConfig,
    persons_probe: PersonsProbe,
    clickhouse_probe: ClickHouseProbe,
    now: datetime,
) -> tuple[list[DormancyVerdict], list[WorkUnit]]:
    """Score the largest tenants; return every verdict and the delete units for approved eligible teams."""
    verdicts: list[DormancyVerdict] = []
    for tenant in top_teams(cursor, config.dormant_top_n):
        if tenant.team_id in config.never_delete_team_ids:
            continue
        signals = score_team(
            cursor, tenant.team_id, tenant.est_rows, config.dormant_days, persons_probe, clickhouse_probe
        )
        verdicts.append(evaluate(signals, config.dormant_days, now))
    approved = set(config.dormant_approved_team_ids)
    units = [dormant_unit(v) for v in verdicts if v.eligible and v.signals.team_id in approved]
    return verdicts, units


@dagster.op(out={"scorecard": dagster.Out(str), "result": dagster.Out(ModeResult)})
def run_dormant_op(
    context: dagster.OpExecutionContext,
    config: EventPropertyCleanupConfig,
    preflight: PreflightReport,
    previous: ModeResult,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    persons_database_reader: dagster.ResourceParam[psycopg2.extensions.connection],
) -> Iterator[dagster.Output]:
    if not config.dormant_discovery_enabled:
        context.log.info("dormant-tenant discovery disabled")
        yield dagster.Output("", output_name="scorecard", metadata={"scored": 0})
        yield dagster.Output(_skipped("dormant"), output_name="result")
        return

    clickhouse_probe = clickhouse_probe_for(cluster)
    with discovery_cursor(config) as cursor:
        verdicts, units = score_dormant_teams(
            cursor,
            config,
            persons_probe_for(persons_database_reader, config.dormant_persons_probe_timeout),
            clickhouse_probe,
            datetime.now(UTC),
        )
    csv_text = scorecard_csv(verdicts)
    context.log.info("dormancy scorecard\n%s", csv_text)
    eligible = [v.signals.team_id for v in verdicts if v.eligible]
    yield dagster.Output(
        csv_text,
        output_name="scorecard",
        metadata={
            "scored": len(verdicts),
            "eligible_team_ids": str(eligible),
            "eligible_but_not_approved": str([t for t in eligible if t not in config.dormant_approved_team_ids]),
            "approved_and_deleting": str([u.team_id for u in units]),
            "scorecard_csv": dagster.MetadataValue.md(f"```\n{csv_text}\n```"),
        },
    )

    def revalidator(unit: WorkUnit) -> Callable[[], bool]:
        def check() -> bool:
            with discovery_cursor(config) as cursor:
                ok = still_dormant(cursor, unit.team_id, config.dormant_days, clickhouse_probe)
            if not ok:
                context.log.warning("team %s is no longer dormant; stopping its unit", unit.team_id)
            return ok

        return check

    yield dagster.Output(
        run_units(context, config, preflight, "dormant", iter(units), cluster, revalidator),
        output_name="result",
    )


@dagster.op
def collect_and_vacuum_op(
    context: dagster.OpExecutionContext,
    config: EventPropertyCleanupConfig,
    pollution: ModeResult,
    retention: ModeResult,
    dormant: ModeResult,
) -> dict[str, int]:
    results = [pollution, retention, dormant]
    rows_since_vacuum = sum(r.rows_since_vacuum for r in results)
    final_vacuums = 0
    if config.vacuum and not config.dry_run and rows_since_vacuum > 0:
        notices = DjangoPostgresBackend().vacuum(config.vacuum_cost_delay_ms, config.vacuum_cost_limit)
        context.log.info("final vacuum: %s", notices[-12:])
        final_vacuums = 1
    summary = {
        "units": sum(r.units for r in results),
        "rows_deleted": sum(r.rows_deleted for r in results),
        "estimated_rows": sum(r.estimated_rows for r in results),
        "pauses": sum(r.pauses for r in results),
        "vacuums": sum(r.vacuums for r in results) + final_vacuums,
        "stopped_units": sum(r.stopped_units for r in results),
    }
    context.add_output_metadata({k: dagster.MetadataValue.int(v) for k, v in summary.items()})
    return summary


# One pod for the whole run: the ops are strictly sequential, the table is on the shared cloud primary,
# and every unit is resumable by relaunch, so per-step pods would only add cost.
executor_def = dagster.in_process_executor

OP_NAMES = (
    "preflight_op",
    "run_pollution_op",
    "run_retention_op",
    "run_dormant_op",
    "collect_and_vacuum_op",
)


def fan_out_config(config: dict) -> dict:
    """Every op reads the same EventPropertyCleanupConfig; the launchpad shows it once."""
    shared = EventPropertyCleanupConfig(**config)
    return dagster.RunConfig(ops=dict.fromkeys(OP_NAMES, shared)).to_config_dict()


@dagster.job(
    tags={"owner": JobOwners.TEAM_INGESTION.value},
    executor_def=executor_def,
    config=dagster.ConfigMapping(config_fn=fan_out_config, config_schema=EventPropertyCleanupConfig.to_config_schema()),
)
def eventproperty_cleanup_job():
    """Shrink posthog_eventproperty: pollution rows, stale-event rows and dormant tenants, paced and vacuumed."""
    preflight = preflight_op()
    pollution = run_pollution_op(preflight)
    retention = run_retention_op(preflight, pollution)
    dormant = run_dormant_op(preflight, retention)
    collect_and_vacuum_op(pollution, retention, dormant.result)
