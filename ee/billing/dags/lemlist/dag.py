"""Dagster asset, job, and schedule that run the Lemlist → Duckgres ETL.

The pipeline is small enough (~100 campaigns, two resources) that a single
asset is sufficient; we don't need the graph_asset/DynamicOutput fan-out used
in ``customer_archetype.py``. A daily 06:00 UTC schedule lines the snapshots
up nicely — late enough to capture the prior day's activity, early enough that
downstream dashboards have fresh data by the start of the work day.
"""

from datetime import UTC, date, datetime

import dagster

from posthog.dags.common import JobOwners

from .auth import LemlistAuthResource
from .destination import LEMLIST_DATASET_NAME, build_pipeline, scoped_snake_case_naming
from .source import DEFAULT_STATS_BATCH_SIZE, lemlist_source

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
    """Fetch Lemlist campaigns + stats and append a snapshot to Duckgres."""
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
        info = pipeline.run(source)

    context.log.info("Pipeline load info:\n%s", info)
    context.add_output_metadata(
        {
            "dataset": dagster.MetadataValue.text(LEMLIST_DATASET_NAME),
            "snapshot_date": dagster.MetadataValue.text(snapshot_date.isoformat()),
            "load_info": dagster.MetadataValue.json(info.asdict()),
        }
    )

    if info.has_failed_jobs:
        raise dagster.Failure(
            description="dlt pipeline reported failed load jobs",
            metadata={"load_info": dagster.MetadataValue.json(info.asdict())},
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
    # Binding ``snapshot_date`` to the schedule's tick time (rather than the
    # asset's own ``datetime.now(UTC).date()`` fallback) makes catch-up ticks
    # and manual replays idempotent: the ``run_key`` deduplicates repeated
    # ticks for the same day, and the explicit ``snapshot_date`` guarantees
    # the row is stamped with the intended date even if the run executes
    # after midnight UTC.
    snapshot_date = context.scheduled_execution_time.date().isoformat()
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
