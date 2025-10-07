"""
Dagster asset and automation for experiment regular metrics timeseries analysis.

This module defines:
- One asset (experiment_regular_metrics_timeseries) with dynamic partitions for experiment-metric combinations
- Automatic discovery and processing of new experiment-regular metric combinations
- Sensors and schedules for continuous timeseries calculation
"""

import json
from datetime import datetime, time
from typing import Any, Union
from zoneinfo import ZoneInfo

from django.db.models import Q

import dagster

from posthog.schema import (
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentQuery,
    ExperimentQueryResponse,
    ExperimentRatioMetric,
)

from posthog.hogql_queries.experiments.experiment_metric_fingerprint import compute_metric_fingerprint
from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.models.experiment import Experiment, ExperimentMetricResult
from posthog.models.team import Team

from dags.common import JobOwners

# =============================================================================
# Configuration
# =============================================================================

# Default hour (UTC) for experiment recalculation when team has no specific time set
DEFAULT_EXPERIMENT_RECALCULATION_HOUR = 2  # 02:00 UTC

# Create dynamic partitions definition for regular metric combinations
EXPERIMENT_REGULAR_METRICS_PARTITIONS_NAME = "experiment_regular_metrics"
experiment_regular_metrics_partitions_def = dagster.DynamicPartitionsDefinition(
    name=EXPERIMENT_REGULAR_METRICS_PARTITIONS_NAME
)

# =============================================================================
# Asset
# =============================================================================


def _get_experiment_regular_metrics_timeseries(
    context: dagster.SensorEvaluationContext,
) -> list[tuple[int, str, str, dict[str, Any]]]:
    """
    Discover active experiment-regular metric combinations from the database.

    Each combination will become a dynamic partition for the experiment_regular_metrics_timeseries asset.

    Args:
        context: Dagster context for logging to UI.

    Returns:
        List of tuples containing (experiment_id, metric_uuid, fingerprint, metric_dict)
        for all valid experiment-regular metric combinations that should be processed.
    """
    experiment_metrics = []

    # Query experiments that are eligible for timeseries analysis (running experiments only)
    experiments = Experiment.objects.filter(
        deleted=False,
        stats_config__timeseries=True,
        start_date__isnull=False,
        end_date__isnull=True,
    ).exclude(
        # Exclude if both metrics and metrics_secondary are empty or null
        Q(metrics__isnull=True) | Q(metrics=[]),
        Q(metrics_secondary__isnull=True) | Q(metrics_secondary=[]),
    )

    for experiment in experiments:
        # Extract regular metrics from metrics and metrics_secondary fields
        all_metrics = (experiment.metrics or []) + (experiment.metrics_secondary or [])

        for metric in all_metrics:
            # Skip if metric doesn't have a UUID (shouldn't happen but being safe)
            metric_uuid = metric.get("uuid")
            if not metric_uuid:
                context.log.warning(f"Metric in experiment {experiment.id} has no UUID, skipping")
                continue

            # Compute fingerprint for this metric in context of this experiment
            fingerprint = compute_metric_fingerprint(
                metric,
                experiment.start_date,
                experiment.stats_config,
                experiment.exposure_criteria,
            )

            experiment_metrics.append((experiment.id, metric_uuid, fingerprint, metric))

    return experiment_metrics


def _remove_step_sessions_from_experiment_result(result: ExperimentQueryResponse) -> ExperimentQueryResponse:
    """
    Remove step_sessions values from experiment results to reduce API response size.
    """
    if result.baseline is not None:
        result.baseline.step_sessions = None

    if result.variant_results is not None:
        for variant in result.variant_results:
            variant.step_sessions = None

    return result


def _parse_partition_key(partition_key: str) -> tuple[int, str, str]:
    """
    Parse partition key to extract experiment ID, metric UUID, and fingerprint.

    The partition key format is: experiment_{id}_metric_{uuid}_{fingerprint}
    """
    parts = partition_key.split("_")
    if len(parts) != 5 or parts[0] != "experiment" or parts[2] != "metric":
        raise ValueError(f"Invalid partition key format: {partition_key}")

    try:
        experiment_id = int(parts[1])
        metric_uuid = parts[3]
        fingerprint = parts[4]
        return experiment_id, metric_uuid, fingerprint
    except ValueError as e:
        raise ValueError(f"Failed to parse partition key {partition_key}: {e}")


@dagster.asset(
    partitions_def=experiment_regular_metrics_partitions_def,
    group_name="experiments",
    tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
)
def experiment_regular_metrics_timeseries(context: dagster.AssetExecutionContext) -> dict[str, Any]:
    """
    Calculate timeseries analysis results for a specific experiment-regular metric combination.

    This is a single asset with dynamic partitions - one partition per experiment-regular metric
    combination. Each partition computes timeseries analysis for one regular metric from one
    experiment using ExperimentQueryRunner.
    """
    # Parse partition key to get experiment and metric info
    if not context.partition_key:
        raise dagster.Failure("This asset must be run with a partition key")

    experiment_id, metric_uuid, fingerprint = _parse_partition_key(context.partition_key)

    context.log.info(
        f"Computing timeseries results for experiment {experiment_id}, metric {metric_uuid}, fingerprint {fingerprint}"
    )

    # Load experiment from database
    try:
        experiment = Experiment.objects.get(id=experiment_id, deleted=False)
    except Experiment.DoesNotExist:
        raise dagster.Failure(f"Experiment {experiment_id} not found or deleted")

    # Find the metric with matching UUID in experiment's metrics
    all_metrics = (experiment.metrics or []) + (experiment.metrics_secondary or [])
    metric_dict = None
    for metric in all_metrics:
        if metric.get("uuid") == metric_uuid:
            metric_dict = metric
            break

    if not metric_dict:
        raise dagster.Failure(f"Metric {metric_uuid} not found in experiment {experiment_id}")

    # Convert metric dict to appropriate Pydantic model
    try:
        metric_type = metric_dict.get("metric_type")
        metric_obj: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]
        if metric_type == "mean":
            metric_obj = ExperimentMeanMetric(**metric_dict)
        elif metric_type == "funnel":
            metric_obj = ExperimentFunnelMetric(**metric_dict)
        elif metric_type == "ratio":
            metric_obj = ExperimentRatioMetric(**metric_dict)
        else:
            raise dagster.Failure(f"Unknown metric type: {metric_type}")

        experiment_query = ExperimentQuery(
            experiment_id=experiment_id,
            metric=metric_obj,
        )

        # Cumulative calculation: from experiment start to current time
        if not experiment.start_date:
            raise dagster.Failure(
                f"Experiment {experiment_id} has no start_date - only launched experiments should be processed"
            )
        query_from_utc = experiment.start_date
        query_to_utc = datetime.now(ZoneInfo("UTC"))

        query_runner = ExperimentQueryRunner(query=experiment_query, team=experiment.team)
        result = query_runner._calculate()

        result = _remove_step_sessions_from_experiment_result(result)

        completed_at = datetime.now(ZoneInfo("UTC"))

        # Store the result in the database
        experiment_metric_result, created = ExperimentMetricResult.objects.update_or_create(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            query_to=query_to_utc,
            defaults={
                "query_from": query_from_utc,
                "status": ExperimentMetricResult.Status.COMPLETED,
                "result": result.model_dump(),
                "query_id": None,
                "completed_at": completed_at,
                "error_message": None,
            },
        )

        # Add metadata for Dagster UI display
        context.add_output_metadata(
            metadata={
                "experiment_id": experiment_id,
                "experiment_metric_result_id": experiment_metric_result.id,
                "metric_uuid": metric_uuid,
                "fingerprint": fingerprint,
                "metric_type": metric_type,
                "metric_name": metric_dict.get("name", f"Metric {metric_uuid}"),
                "experiment_name": experiment.name,
                "experiment_start_date": experiment.start_date.isoformat() if experiment.start_date else None,
                "experiment_exposure_criteria": json.dumps(experiment.exposure_criteria)
                if experiment.exposure_criteria
                else None,
                "metric_definition": str(metric_dict),
                "query_from": query_from_utc.isoformat(),
                "query_to": query_to_utc.isoformat(),
                "results_status": "success",
            }
        )
        return {
            "experiment_id": experiment_id,
            "metric_uuid": metric_uuid,
            "fingerprint": fingerprint,
            "metric_definition": metric_dict,
            "query_from": query_from_utc.isoformat(),
            "query_to": query_to_utc.isoformat(),
            "result": result.model_dump(),
        }

    except Exception as e:
        if not experiment.start_date:
            raise dagster.Failure(
                f"Experiment {experiment_id} has no start_date - only launched experiments should be processed"
            )
        query_from_utc = experiment.start_date
        query_to_utc = datetime.now(ZoneInfo("UTC"))

        ExperimentMetricResult.objects.update_or_create(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            query_to=query_to_utc,
            defaults={
                "query_from": query_from_utc,
                "status": ExperimentMetricResult.Status.FAILED,
                "result": None,
                "query_id": None,
                "completed_at": None,
                "error_message": str(e),
            },
        )

        raise dagster.Failure(f"Failed to compute timeseries: {e}")


# =============================================================================
# Job and automation for regular metrics timeseries calculation
# =============================================================================

experiment_regular_metrics_timeseries_job = dagster.define_asset_job(
    name="experiment_regular_metrics_timeseries_job",
    selection=[experiment_regular_metrics_timeseries],
    tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
)


@dagster.sensor(
    job=experiment_regular_metrics_timeseries_job,
    minimum_interval_seconds=30,
    tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
)
def experiment_regular_metrics_timeseries_discovery_sensor(context: dagster.SensorEvaluationContext):
    """
    Automatically discover new experiment-regular metric combinations and trigger timeseries calculation.

    This sensor continuously monitors for new experiments or regular metrics that need timeseries
    analysis. When new combinations are found, it creates dynamic partitions for the
    experiment_regular_metrics_timeseries asset and triggers processing only for the new partitions.
    """
    try:
        current_experiment_metrics = _get_experiment_regular_metrics_timeseries(context)
        if not current_experiment_metrics:
            context.log.debug("No experiment-regular metrics found for timeseries analysis")
            return dagster.SkipReason("No experiments with regular metrics found")

        # Generate partition keys in format: experiment_{id}_metric_{uuid}_{fingerprint}
        current_partition_keys = [
            f"experiment_{exp_id}_metric_{metric_uuid}_{fingerprint}"
            for exp_id, metric_uuid, fingerprint, _ in current_experiment_metrics
        ]

        # Check which partitions are new
        existing_partitions = set(context.instance.get_dynamic_partitions(EXPERIMENT_REGULAR_METRICS_PARTITIONS_NAME))
        new_partitions = [key for key in current_partition_keys if key not in existing_partitions]

        # Build response
        run_requests = []
        dynamic_partitions_requests = []

        if new_partitions:
            context.log.info(
                f"Discovered {len(new_partitions)} new experiment-regular metric combinations for timeseries analysis"
            )
            # Add new partitions
            dynamic_partitions_requests.append(
                experiment_regular_metrics_partitions_def.build_add_request(new_partitions)
            )
            # Create run requests for new partitions only
            run_requests = [
                dagster.RunRequest(
                    run_key=f"sensor_{partition_key}_{context.cursor or 'initial'}",
                    partition_key=partition_key,
                )
                for partition_key in new_partitions
            ]
        else:
            context.log.debug("No new experiment-regular metrics discovered for timeseries analysis")
            return dagster.SkipReason("No new regular metric experiments to process")

        return dagster.SensorResult(
            run_requests=run_requests,
            dynamic_partitions_requests=dynamic_partitions_requests,
        )

    except Exception as e:
        context.log.exception("Failed to discover regular metric experiments")
        return dagster.SkipReason(f"Failed to discover regular metric experiments: {e}")


@dagster.schedule(
    job=experiment_regular_metrics_timeseries_job,
    cron_schedule="0 * * * *",  # Every hour at minute 0
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
)
def experiment_regular_metrics_timeseries_refresh_schedule(context: dagster.ScheduleEvaluationContext):
    """
    This schedule runs hourly and reprocesses experiment-regular metric combinations
    for teams scheduled at the current hour.
    """
    try:
        current_hour = context.scheduled_execution_time.hour
        target_time = time(current_hour, 0, 0)

        # Build time filter for teams
        if current_hour == DEFAULT_EXPERIMENT_RECALCULATION_HOUR:
            # At default hour, include teams with NULL (not set) or explicitly set to this hour
            time_filter = Q(experiment_recalculation_time=target_time) | Q(experiment_recalculation_time__isnull=True)
        else:
            # At other hours, only include teams explicitly set to this hour
            time_filter = Q(experiment_recalculation_time=target_time)

        # Get all experiments from teams scheduled at this hour
        target_experiment_ids = set(
            Experiment.objects.filter(
                deleted=False,
                stats_config__timeseries=True,
                start_date__isnull=False,
                end_date__isnull=True,
                team__in=Team.objects.filter(time_filter),
            ).values_list("id", flat=True)
        )

        if not target_experiment_ids:
            return dagster.SkipReason(f"No experiments found for teams scheduled at {current_hour}:00 UTC")

        all_partitions = list(context.instance.get_dynamic_partitions(EXPERIMENT_REGULAR_METRICS_PARTITIONS_NAME))

        if not all_partitions:
            return dagster.SkipReason("No experiment regular metrics partitions exist")

        # Filter to only partitions for target experiments
        partitions_to_run = []
        for partition_key in all_partitions:
            try:
                experiment_id, _, _ = _parse_partition_key(partition_key)
                if experiment_id in target_experiment_ids:
                    partitions_to_run.append(partition_key)
            except ValueError:
                context.log.warning(f"Skipping partition with invalid key format: {partition_key}")
                continue

        if not partitions_to_run:
            return dagster.SkipReason(f"No metrics to process for teams at {current_hour}:00 UTC")

        context.log.info(
            f"Scheduling refresh for {len(partitions_to_run)} partitions for teams at {current_hour}:00 UTC"
        )

        return [
            dagster.RunRequest(
                run_key=f"scheduled_{partition_key}_{context.scheduled_execution_time.strftime('%Y%m%d_%H')}",
                partition_key=partition_key,
            )
            for partition_key in partitions_to_run
        ]

    except Exception as e:
        context.log.exception("Failed to schedule regular metrics refresh")
        return dagster.SkipReason(f"Failed to schedule regular metrics refresh: {e}")
