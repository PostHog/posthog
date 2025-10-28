"""
Dagster asset and automation for experiment timeseries recalculation.

This module allows users to recalculate historical timeseries data for experiments
when they need to regenerate data after changes or fixes.
"""

import time as time_module
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import dagster
from dagster import AssetExecutionContext, RetryPolicy, RunRequest, SkipReason

from posthog.schema import ExperimentFunnelMetric, ExperimentMeanMetric, ExperimentQuery, ExperimentRatioMetric

from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.models.experiment import ExperimentMetricResult, ExperimentTimeseriesRecalculation

from dags.common import JobOwners
from dags.experiments import remove_step_sessions_from_experiment_result

experiment_timeseries_recalculation_partitions_def = dagster.DynamicPartitionsDefinition(
    name="experiment_recalculations"
)


def parse_partition_key(partition_key: str) -> tuple[str, int, str, str]:
    """
    Parse a recalculation partition key into its components.

    Expected format: "recalculation_{recalc_id}_experiment_{experiment_id}_metric_{metric_uuid}_{fingerprint}"
    """
    parts = partition_key.split("_")

    if len(parts) < 6 or parts[0] != "recalculation" or parts[2] != "experiment" or parts[4] != "metric":
        raise ValueError(f"Invalid partition key format: {partition_key}")

    try:
        recalculation_id = parts[1]
        experiment_id = int(parts[3])
        metric_uuid = parts[5]
        fingerprint = "_".join(parts[6:])
        return recalculation_id, experiment_id, metric_uuid, fingerprint
    except ValueError as e:
        raise ValueError(f"Failed to parse partition key {partition_key}: {e}")


def get_metric(metric_data):
    """Build metric object from metric data."""
    metric_type = metric_data.get("metric_type")

    if metric_type == "mean":
        return ExperimentMeanMetric(**metric_data)
    elif metric_type == "funnel":
        return ExperimentFunnelMetric(**metric_data)
    elif metric_type == "ratio":
        return ExperimentRatioMetric(**metric_data)
    else:
        raise dagster.Failure(f"Unknown metric type: {metric_type}")


@dagster.asset(
    partitions_def=experiment_timeseries_recalculation_partitions_def,
    group_name="experiments",
    tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
    retry_policy=RetryPolicy(max_retries=2, delay=300),
)
def experiment_timeseries_recalculation(context: AssetExecutionContext) -> dict[str, Any]:
    """
    Process entire experiment recalculation with resumability.

    Each partition processes one recalculation request, calculating timeseries data
    for each day in the experiment's date range. Supports resuming from the
    last successful date if the job fails and is retried.
    """
    recalculation_id, experiment_id_from_key, metric_uuid_from_key, fingerprint_from_key = parse_partition_key(
        context.partition_key
    )

    context.log.info(
        f"Starting recalculation {recalculation_id} for experiment {experiment_id_from_key}, "
        f"metric {metric_uuid_from_key}, fingerprint {fingerprint_from_key}"
    )

    try:
        recalculation_request = ExperimentTimeseriesRecalculation.objects.get(id=recalculation_id)
    except ExperimentTimeseriesRecalculation.DoesNotExist:
        raise dagster.Failure(f"Recalculation request {recalculation_id} not found")

    if recalculation_request.status == ExperimentTimeseriesRecalculation.Status.PENDING:
        recalculation_request.status = ExperimentTimeseriesRecalculation.Status.IN_PROGRESS
        recalculation_request.save(update_fields=["status"])

    experiment = recalculation_request.experiment
    if not experiment.start_date:
        raise dagster.Failure(f"Experiment {experiment.id} has no start_date")

    # Convert experiment dates from UTC to team timezone for correct daily boundaries
    team_tz = ZoneInfo(experiment.team.timezone) if experiment.team.timezone else ZoneInfo("UTC")
    start_date = experiment.start_date.astimezone(team_tz).date()

    if experiment.end_date:
        end_date = experiment.end_date.astimezone(team_tz).date()
    else:
        end_date = datetime.now(team_tz).date()

    # Resume from last successful date or start fresh
    if recalculation_request.last_successful_date:
        current_date = recalculation_request.last_successful_date + timedelta(days=1)
        context.log.info(f"Resuming recalculation from {current_date}")
    else:
        current_date = start_date
        context.log.info(f"Starting fresh recalculation from {current_date}")

    metric_obj = get_metric(recalculation_request.metric)
    experiment_query = ExperimentQuery(experiment_id=experiment.id, metric=metric_obj)
    fingerprint = recalculation_request.fingerprint

    days_processed = 0
    date_range_delta = end_date - start_date
    total_days = date_range_delta.days + 1

    while current_date <= end_date:
        try:
            day_num = (current_date - start_date).days + 1
            context.log.info(f"Processing day {day_num}/{total_days}: {current_date}")

            # Create end-of-day timestamp in team timezone, then convert to UTC for ExperimentQueryRunner
            end_of_day_team_tz = datetime.combine(current_date + timedelta(days=1), time(0, 0, 0)).replace(
                tzinfo=team_tz
            )
            query_to_utc = end_of_day_team_tz.astimezone(ZoneInfo("UTC"))

            query_runner = ExperimentQueryRunner(
                query=experiment_query, team=experiment.team, override_end_date=query_to_utc
            )
            result = query_runner._calculate()
            result = remove_step_sessions_from_experiment_result(result)

            ExperimentMetricResult.objects.update_or_create(
                experiment_id=experiment.id,
                metric_uuid=recalculation_request.metric.get("uuid"),
                query_to=query_to_utc,
                defaults={
                    "fingerprint": fingerprint,
                    "query_from": experiment.start_date,
                    "status": ExperimentMetricResult.Status.COMPLETED,
                    "result": result.model_dump(),
                    "query_id": None,
                    "completed_at": datetime.now(ZoneInfo("UTC")),
                    "error_message": None,
                },
            )

            recalculation_request.last_successful_date = current_date
            recalculation_request.save(update_fields=["last_successful_date"])
            days_processed += 1

            progress_pct = round((day_num / total_days) * 100, 1)
            context.log.info(f"Progress: {progress_pct}% ({day_num}/{total_days} days)")

        except Exception as e:
            context.log.exception(f"Failed on {current_date}: {e}")
            recalculation_request.status = ExperimentTimeseriesRecalculation.Status.FAILED
            recalculation_request.save(update_fields=["status"])

            raise dagster.Failure(
                f"Recalculation failed on {current_date}",
                metadata={
                    "failed_date": current_date.isoformat(),
                    "days_completed": days_processed,
                    "total_days": total_days,
                    "error": str(e),
                },
            )

        current_date += timedelta(days=1)

    recalculation_request.status = ExperimentTimeseriesRecalculation.Status.COMPLETED
    recalculation_request.save(update_fields=["status"])
    context.log.info(f"Recalculation {recalculation_id} completed successfully")

    context.add_output_metadata(
        {
            "recalculation_id": recalculation_id,
            "experiment_id": experiment.id,
            "metric_uuid": recalculation_request.metric.get("uuid"),
            "days_processed": days_processed,
            "total_days": total_days,
            "progress_percentage": 100.0,
            "date_range": f"{start_date} to {end_date}",
        }
    )

    return {
        "recalculation_id": str(recalculation_id),
        "experiment_id": experiment.id,
        "metric_uuid": recalculation_request.metric.get("uuid"),
        "days_processed": days_processed,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }


experiment_timeseries_recalculation_job = dagster.define_asset_job(
    name="experiment_timeseries_recalculation_job",
    selection=[experiment_timeseries_recalculation],
    tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
)


@dagster.sensor(
    job=experiment_timeseries_recalculation_job,
    minimum_interval_seconds=30,
    tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
)
def experiment_timeseries_recalculation_sensor(context: dagster.SensorEvaluationContext):
    """
    Discover pending recalculation requests and create partitions to process them.

    This sensor runs every 30 seconds, finds new PENDING recalculation requests,
    creates dynamic partitions for them, and triggers their execution.
    """
    # Track which recalculation requests we've already processed
    last_processed_id = context.cursor

    filter_kwargs: dict[str, Any] = {"status": ExperimentTimeseriesRecalculation.Status.PENDING}
    if last_processed_id:
        filter_kwargs["id__gt"] = last_processed_id

    new_recalculations = list(
        ExperimentTimeseriesRecalculation.objects.filter(**filter_kwargs).order_by("id")[:100]
    )  # Limit to 100 requests at a time

    if not new_recalculations:
        return SkipReason("No new recalculation requests")

    context.log.info(f"Found {len(new_recalculations)} new recalculation requests")

    partition_keys = []
    latest_id = last_processed_id or ""

    for recalc_request in new_recalculations:
        metric_uuid = recalc_request.metric.get("uuid", "unknown")
        partition_key = (
            f"recalculation_{recalc_request.id}_"
            f"experiment_{recalc_request.experiment_id}_"
            f"metric_{metric_uuid}_{recalc_request.fingerprint}"
        )
        partition_keys.append(partition_key)
        latest_id = max(latest_id, str(recalc_request.id))
        context.log.info(f"Creating partition {partition_key}")

    context.instance.add_dynamic_partitions("experiment_recalculations", partition_keys)
    context.update_cursor(latest_id)

    run_requests = []
    for partition_key in partition_keys:
        recalculation_id, experiment_id, metric_uuid, fingerprint = parse_partition_key(partition_key)
        run_requests.append(
            RunRequest(
                run_key=f"recalculation_{recalculation_id}_{int(time_module.time())}",
                partition_key=partition_key,
                tags={
                    "recalculation_id": str(recalculation_id),
                    "experiment_id": str(experiment_id),
                    "metric_uuid": metric_uuid,
                    "fingerprint": fingerprint,
                    "triggered_at": datetime.now(ZoneInfo("UTC")).isoformat(),
                },
            )
        )

    return run_requests
