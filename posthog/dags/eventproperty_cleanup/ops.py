"""Dagster ops and job for the posthog_eventproperty cleanup crawler.

Manual-only: no schedule, no sensor, dry run by default. Launch from the Dagster launchpad.
"""

from collections.abc import Iterator
from datetime import UTC, datetime

from django.conf import settings
from django.db import connection

import dagster
import psycopg2
from dagster_k8s import k8s_job_executor

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.custom_metrics import MetricsClient
from posthog.dags.common import JobOwners
from posthog.dataclasses import frozen

from . import sql
from .config import EventPropertyCleanupConfig
from .dormancy import (
    DormancyVerdict,
    clickhouse_probe_for,
    dormant_unit,
    evaluate,
    persons_probe_for,
    score_team,
    scorecard_csv,
    top_teams,
)
from .engine import DeleteEngine, DjangoPostgresBackend, UnitResult
from .units import WorkUnit, discover_pollution_units, discover_retention_units


@frozen
class PreflightReport:
    database: str
    is_primary: bool
    indexes: tuple[str, ...]
    replication_slots: tuple[str, ...]
    vacuumed: bool


def _region() -> str:
    return str(getattr(settings, "CLOUD_DEPLOYMENT", None) or "local")


@dagster.op
def preflight_op(context: dagster.OpExecutionContext, config: EventPropertyCleanupConfig) -> PreflightReport:
    with connection.cursor() as cursor:
        cursor.execute(sql.PREFLIGHT_PRIMARY)
        in_recovery, database = cursor.fetchone()
        cursor.execute(sql.PREFLIGHT_INDEXES, {"table": sql.TABLE})
        indexes = tuple(sorted(row[0] for row in cursor.fetchall()))
        cursor.execute(sql.PREFLIGHT_REPLICATION_SLOTS)
        slots = tuple(f"{row[0]}(active={row[1]})" for row in cursor.fetchall())

    if config.require_primary and in_recovery:
        raise dagster.Failure(f"{database} is a replica; the cleanup needs the primary")
    missing = [name for name in sql.REQUIRED_INDEXES if name not in indexes]
    if missing:
        raise dagster.Failure(f"required indexes missing on {sql.TABLE}: {missing}")
    if config.require_no_replication_slots and slots:
        raise dagster.Failure(
            f"replication slots exist: {slots}. A logical slot would retain every byte of WAL this job writes."
        )

    vacuumed = False
    if config.vacuum_on_start and config.vacuum and not config.dry_run:
        notices = DjangoPostgresBackend().vacuum(config.vacuum_cost_delay_ms, config.vacuum_cost_limit)
        context.log.info("preflight vacuum: %s", notices[-12:])
        vacuumed = True

    report = PreflightReport(
        database=database,
        is_primary=not in_recovery,
        indexes=indexes,
        replication_slots=slots,
        vacuumed=vacuumed,
    )
    context.add_output_metadata(
        {
            "database": database,
            "is_primary": not in_recovery,
            "indexes": ", ".join(indexes),
            "replication_slots": ", ".join(slots) or "none",
            "dry_run": config.dry_run,
        }
    )
    return report


def _emit_units(
    context: dagster.OpExecutionContext, units: list[WorkUnit], output_name: str = "result"
) -> Iterator[dagster.DynamicOutput]:
    # Dynamic outputs cannot carry op-level metadata, so the summary goes to the log and each
    # output carries its own estimate.
    context.log.info(
        "%d units over %d teams, ~%s rows estimated",
        len(units),
        len({u.team_id for u in units}),
        f"{sum(u.est_rows for u in units):,}",
    )
    for unit in units[:50]:
        context.log.info("unit %s ~%s rows (%s)", unit.label, f"{unit.est_rows:,}", unit.reason)
    for index, unit in enumerate(units):
        yield dagster.DynamicOutput(
            unit,
            mapping_key=f"{unit.mode}_{index}",
            output_name=output_name,
            metadata={"label": unit.label, "estimated_rows": unit.est_rows, "reason": unit.reason},
        )


@dagster.op(out=dagster.DynamicOut(WorkUnit))
def discover_pollution_op(
    context: dagster.OpExecutionContext, config: EventPropertyCleanupConfig, preflight: PreflightReport
) -> Iterator[dagster.DynamicOutput]:
    if not config.pollution_enabled:
        context.log.info("pollution mode disabled")
        return
    with connection.cursor() as cursor:
        units = list(discover_pollution_units(cursor, config))
    yield from _emit_units(context, units)


@dagster.op(out=dagster.DynamicOut(WorkUnit))
def discover_retention_op(
    context: dagster.OpExecutionContext, config: EventPropertyCleanupConfig, preflight: PreflightReport
) -> Iterator[dagster.DynamicOutput]:
    if config.retention_days is None:
        context.log.info("retention mode disabled (retention_days is None)")
        return
    with connection.cursor() as cursor:
        units = list(discover_retention_units(cursor, config))
    yield from _emit_units(context, units)


def score_dormant_teams(
    cursor,
    config: EventPropertyCleanupConfig,
    persons_probe,
    clickhouse_probe,
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


@dagster.op(out={"scorecard": dagster.Out(str), "units": dagster.DynamicOut(WorkUnit)})
def score_dormant_teams_op(
    context: dagster.OpExecutionContext,
    config: EventPropertyCleanupConfig,
    preflight: PreflightReport,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    persons_database_reader: dagster.ResourceParam[psycopg2.extensions.connection],
) -> Iterator[dagster.Output | dagster.DynamicOutput]:
    if not config.dormant_discovery_enabled:
        context.log.info("dormant-tenant discovery disabled")
        yield dagster.Output("", output_name="scorecard", metadata={"scored": 0})
        return
    with connection.cursor() as cursor:
        verdicts, units = score_dormant_teams(
            cursor,
            config,
            persons_probe_for(persons_database_reader, config.dormant_persons_probe_timeout),
            clickhouse_probe_for(cluster),
            datetime.now(UTC),
        )
    csv_text = scorecard_csv(verdicts)
    context.log.info("dormancy scorecard\n%s", csv_text)
    eligible = [v.signals.team_id for v in verdicts if v.eligible]
    unapproved = [t for t in eligible if t not in config.dormant_approved_team_ids]
    yield dagster.Output(
        csv_text,
        output_name="scorecard",
        metadata={
            "scored": len(verdicts),
            "eligible_team_ids": str(eligible),
            "eligible_but_not_approved": str(unapproved),
            "approved_and_deleting": str([u.team_id for u in units]),
            "scorecard_csv": dagster.MetadataValue.md(f"```\n{csv_text}\n```"),
        },
    )
    yield from _emit_units(context, units, output_name="units")


@dagster.op
def delete_unit_op(
    context: dagster.OpExecutionContext,
    config: EventPropertyCleanupConfig,
    unit: WorkUnit,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> UnitResult:
    if unit.team_id in config.never_delete_team_ids:
        raise dagster.Failure(f"{unit.label} is on never_delete_team_ids")
    if config.dry_run:
        context.log.info("dry run: would delete ~%s rows for %s", unit.est_rows, unit.label)
        return UnitResult(
            mode=unit.mode,
            team_id=unit.team_id,
            label=unit.label,
            est_rows=unit.est_rows,
            rows_deleted=0,
            batches=0,
            pauses=0,
            vacuums=0,
            seconds=0.0,
            rows_since_vacuum=0,
            stopped_reason="dry_run",
        )
    engine = DeleteEngine(
        config,
        DjangoPostgresBackend(),
        metrics=MetricsClient(cluster),
        metric_labels={"mode": unit.mode, "region": _region()},
    )
    try:
        result = engine.run_unit(unit)
    except Exception as exc:
        raise dagster.Failure(
            f"{unit.label} failed: {exc}",
            metadata={
                "mode": unit.mode,
                "team_id": unit.team_id,
                "key": str(unit.key),
                "rows_deleted_so_far": engine.rows_deleted_total,
            },
        ) from exc
    context.add_output_metadata(
        {
            "label": result.label,
            "rows_deleted": result.rows_deleted,
            "estimated_rows": result.est_rows,
            "batches": result.batches,
            "pauses": result.pauses,
            "vacuums": result.vacuums,
            "seconds": round(result.seconds, 1),
            "stopped_reason": result.stopped_reason or "exhausted",
        }
    )
    return result


@dagster.op
def collect_and_vacuum_op(
    context: dagster.OpExecutionContext,
    config: EventPropertyCleanupConfig,
    pollution: list[UnitResult],
    retention: list[UnitResult],
    dormant: list[UnitResult],
) -> dict[str, int]:
    results = [*pollution, *retention, *dormant]
    rows_deleted = sum(r.rows_deleted for r in results)
    rows_since_vacuum = sum(r.rows_since_vacuum for r in results)
    if config.vacuum and not config.dry_run and rows_since_vacuum > 0:
        notices = DjangoPostgresBackend().vacuum(config.vacuum_cost_delay_ms, config.vacuum_cost_limit)
        context.log.info("final vacuum: %s", notices[-12:])
    summary = {
        "units": len(results),
        "rows_deleted": rows_deleted,
        "estimated_rows": sum(r.est_rows for r in results),
        "pauses": sum(r.pauses for r in results),
        "vacuums": sum(r.vacuums for r in results),
        "stopped_early": sum(1 for r in results if r.stopped_reason not in (None, "dry_run")),
    }
    context.add_output_metadata({k: dagster.MetadataValue.int(v) for k, v in summary.items()})
    return summary


# One DELETE stream per region: the table is on the shared cloud primary.
executor_def = dagster.in_process_executor if settings.DEBUG else k8s_job_executor.configured({"max_concurrent": 1})

OP_NAMES = (
    "preflight_op",
    "discover_pollution_op",
    "discover_retention_op",
    "score_dormant_teams_op",
    "delete_pollution_unit",
    "delete_retention_unit",
    "delete_dormant_unit",
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
    pollution = discover_pollution_op(preflight).map(delete_unit_op.alias("delete_pollution_unit"))
    retention = discover_retention_op(preflight).map(delete_unit_op.alias("delete_retention_unit"))
    dormant = score_dormant_teams_op(preflight).units.map(delete_unit_op.alias("delete_dormant_unit"))
    collect_and_vacuum_op(pollution.collect(), retention.collect(), dormant.collect())
