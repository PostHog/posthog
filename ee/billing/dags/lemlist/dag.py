"""Dagster asset, job, and schedule that run the Lemlist → Duckgres ETL.
A daily 06:00 UTC schedule lines the snapshots
up nicely — late enough that the prior UTC day is fully settled, early enough
that downstream dashboards have fresh data by the start of the work day. Each
tick stamps rows with the previous tick's date, so ``campaign_stats_daily``
rows represent fully-complete UTC days.
"""

import json
from datetime import UTC, date, datetime, timedelta

import dlt
import dagster
from dlt.destinations.exceptions import DatabaseTerminalException, DatabaseUndefinedRelation

from posthog.dags.common import JobOwners

from .auth import LemlistAuthResource
from .destination import LEMLIST_DATASET_NAME, build_pipeline, scoped_snake_case_naming
from .source import DEFAULT_STATS_BATCH_SIZE, lemlist_source

_STATS_TABLE = "campaign_stats_daily"
_STATS_STEPS_TABLE = "campaign_stats_daily__steps"
_MISSING_TABLE_MARKER = "does not exist"


def _is_missing_table_error(exc: Exception) -> bool:
    """Return True when ``exc`` is Ducklake's "table not found" signal."""
    return _MISSING_TABLE_MARKER in str(exc)


LEMLIST_RETRY_POLICY = dagster.RetryPolicy(
    max_retries=2,
    delay=60,
    backoff=dagster.Backoff.EXPONENTIAL,
    jitter=dagster.Jitter.PLUS_MINUS,
)


class LemlistConfig(dagster.Config):
    stats_batch_size: int = DEFAULT_STATS_BATCH_SIZE
    # ISO-format override for backfills. When unset the asset stamps rows with
    # the UTC date at execution time, which is what the daily schedule wants.
    snapshot_date: str | None = None


def _resolve_snapshot_date(override: str | None) -> date:
    if override:
        return date.fromisoformat(override)
    return datetime.now(UTC).date()


def _delete_existing_snapshot(pipeline: dlt.Pipeline, snapshot_date: date) -> None:
    """Remove any prior rows for ``snapshot_date`` so retries and replays are idempotent.

    Ducklake rejects the DDL dlt emits for ``merge`` dispositions (``ALTER TABLE …
    ADD COLUMN … NOT NULL``), so idempotency is implemented here: before each run
    we delete the current ``snapshot_date``'s rows, then the resource appends a
    fresh batch. Child rows must be cleaned up first because they carry a
    ``_dlt_parent_id`` pointing at the parent row. On the very first run both
    tables are absent — ``DatabaseUndefinedRelation`` is the expected signal.
    """
    with pipeline.sql_client() as client:
        if not client.has_dataset():
            return
        stats_table = client.make_qualified_table_name(_STATS_TABLE)
        steps_table = client.make_qualified_table_name(_STATS_STEPS_TABLE)
        try:
            client.execute_sql(
                f"DELETE FROM {steps_table} "
                f"WHERE _dlt_parent_id IN "
                f"(SELECT _dlt_id FROM {stats_table} WHERE snapshot_date = %s)",
                snapshot_date,
            )
        except DatabaseUndefinedRelation:
            pass
        except DatabaseTerminalException as exc:
            if not _is_missing_table_error(exc):
                raise
        try:
            client.execute_sql(
                f"DELETE FROM {stats_table} WHERE snapshot_date = %s",
                snapshot_date,
            )
        except DatabaseUndefinedRelation:
            pass
        except DatabaseTerminalException as exc:
            if not _is_missing_table_error(exc):
                raise


@dagster.asset(
    name="lemlist_campaigns_and_stats",
    group_name="billing",
    tags={"owner": JobOwners.TEAM_BILLING.value},
    retry_policy=LEMLIST_RETRY_POLICY,
)
def lemlist_campaigns_and_stats(
    context: dagster.AssetExecutionContext,
    config: LemlistConfig,
    lemlist_auth: LemlistAuthResource,
) -> None:
    """Fetch Lemlist campaigns + stats and write a daily snapshot to Duckgres.

    The asset deletes any existing rows for ``snapshot_date`` before running so
    retries and replays produce the same table state they would on a first
    successful run.
    """
    snapshot_date = _resolve_snapshot_date(config.snapshot_date)
    context.log.info(
        "Running Lemlist ETL with snapshot_date=%s, stats_batch_size=%d",
        snapshot_date.isoformat(),
        config.stats_batch_size,
    )

    pipeline = build_pipeline()
    source = lemlist_source(
        session_factory=lemlist_auth.build_session,
        snapshot_date=snapshot_date,
        stats_batch_size=config.stats_batch_size,
    )
    with scoped_snake_case_naming():
        _delete_existing_snapshot(pipeline, snapshot_date)
        info = pipeline.run(source)

    context.log.info("Pipeline load info:\n%s", info)
    load_info_json = json.loads(json.dumps(info.asdict(), default=str))
    context.add_output_metadata(
        {
            "dataset": dagster.MetadataValue.text(LEMLIST_DATASET_NAME),
            "snapshot_date": dagster.MetadataValue.text(snapshot_date.isoformat()),
            "load_info": dagster.MetadataValue.json(load_info_json),
        }
    )

    if info.has_failed_jobs:
        raise dagster.Failure(
            description="dlt pipeline reported failed load jobs",
            metadata={"load_info": dagster.MetadataValue.json(load_info_json)},
        )


lemlist_job = dagster.define_asset_job(
    name="lemlist_job",
    selection=["lemlist_campaigns_and_stats"],
    tags={"owner": JobOwners.TEAM_BILLING.value},
)


@dagster.schedule(
    cron_schedule="0 6 * * *",
    job=lemlist_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_BILLING.value},
)
def lemlist_daily_schedule(context: dagster.ScheduleEvaluationContext) -> dagster.RunRequest:
    # Each tick captures the window ``[previous_tick, this_tick)``, so the
    # snapshot is stamped with the previous tick's date — the row represents a
    # fully-complete UTC day rather than the partial day in progress at tick
    # time. Binding to the schedule (rather than the asset's
    # ``datetime.now(UTC).date()`` fallback) also makes catch-up ticks and
    # manual replays idempotent: the ``run_key`` deduplicates repeated ticks
    # for the same day.
    snapshot_date = (context.scheduled_execution_time.date() - timedelta(days=1)).isoformat()
    return dagster.RunRequest(
        run_key=snapshot_date,
        run_config={
            "ops": {
                "lemlist_campaigns_and_stats": {
                    "config": {"snapshot_date": snapshot_date},
                }
            }
        },
    )
