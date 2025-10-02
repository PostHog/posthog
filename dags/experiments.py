"""
Dagster asset and automation for experiment timeseries analysis.

This module defines:
- One asset (experiment_timeseries) with dynamic partitions for experiment-metric combinations
- Automatic discovery and processing of new experiment-metric combinations
- Sensors and schedules for continuous timeseries calculation
"""

import json
from datetime import datetime
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

from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.models.experiment import Experiment, ExperimentMetricResult

from dags.common import JobOwners

# =============================================================================
# Dynamic Partitions Setup
# =============================================================================

# Create dynamic partitions definition for experiment-metric combinations
experiment_timeseries_partitions_def = dagster.DynamicPartitionsDefinition(name="experiment_timeseries")

# =============================================================================
# Asset
# =============================================================================


def _get_experiment_metrics(context: dagster.SensorEvaluationContext) -> list[tuple[int, str, str, dict[str, Any]]]:
    """
    Discover active experiment-metric combinations from the database.

    Each combination will become a dynamic partition for the experiment_timeseries asset.

    Args:
        context: Dagster context for logging to UI.

    Returns:
        List of tuples containing (experiment_id, metric_uuid, fingerprint, metric_dict)
        for all valid experiment-metric combinations that should be processed.
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
        metrics = (experiment.metrics or []) + (experiment.metrics_secondary or [])

        for metric in metrics:
            metric_uuid = metric.get("uuid")
            if not metric_uuid:
                continue
            fingerprint = metric.get("fingerprint")
            if not fingerprint:
                context.log.error(
                    f"Metric {metric_uuid} for experiment {experiment.id} is missing fingerprint. "
                    "Skipping this metric. Metrics must have fingerprints computed during creation/update."
                )
                continue

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
    partitions_def=experiment_timeseries_partitions_def,
    group_name="experiments",
    tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
)
def experiment_timeseries(context: dagster.AssetExecutionContext) -> dict[str, Any]:
    """
    Calculate timeseries analysis results for a specific experiment-metric combination.

    This is a single asset with dynamic partitions - one partition per experiment-metric
    combination. Each partition computes timeseries analysis for one metric from one
    experiment using ExperimentQueryRunner.

    Returns:
        Dictionary containing experiment metadata, metric definition, and timeseries results.
    """
    # Parse partition key to get experiment and metric info
    if not context.partition_key:
        raise dagster.Failure("This asset must be run with a partition key")

    experiment_id, metric_uuid, fingerprint = _parse_partition_key(context.partition_key)

    context.log.info(
        f"Computing timeseries results for experiment {experiment_id}, metric {metric_uuid}, fingerprint {fingerprint}"
    )

    # Load experiment and metric configuration from database
    try:
        experiment = Experiment.objects.get(id=experiment_id, deleted=False)
        all_metrics = (experiment.metrics or []) + (experiment.metrics_secondary or [])
        if not all_metrics or metric_uuid not in [m.get("uuid") for m in all_metrics]:
            raise dagster.Failure(f"Metric UUID {metric_uuid} not found for experiment {experiment_id}")

        metric = next(m for m in all_metrics if m.get("uuid") == metric_uuid)

    except Experiment.DoesNotExist:
        raise dagster.Failure(f"Experiment {experiment_id} not found or deleted")

    metric_type = metric.get("metric_type")
    metric_obj: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]
    if metric_type == "mean":
        metric_obj = ExperimentMeanMetric(**metric)
    elif metric_type == "funnel":
        metric_obj = ExperimentFunnelMetric(**metric)
    elif metric_type == "ratio":
        metric_obj = ExperimentRatioMetric(**metric)
    else:
        raise dagster.Failure(f"Unknown metric type: {metric_type}")

    try:
        experiment_query = ExperimentQuery(
            experiment_id=experiment_id,
            metric=metric_obj,
        )

        # Cumulative calculation: from experiment start to current time
        query_from_utc = experiment.start_date if experiment.start_date else experiment.created_at
        query_to_utc = datetime.now(ZoneInfo("UTC"))

        query_runner = ExperimentQueryRunner(query=experiment_query, team=experiment.team)
        result = query_runner._calculate()

        result = _remove_step_sessions_from_experiment_result(result)

        completed_at = datetime.now(ZoneInfo("UTC"))

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
                "metric_name": metric.get("name", f"Metric {metric_uuid}"),
                "experiment_name": experiment.name,
                "experiment_start_date": experiment.start_date.isoformat() if experiment.start_date else None,
                "experiment_exposure_criteria": json.dumps(experiment.exposure_criteria)
                if experiment.exposure_criteria
                else None,
                "metric_definition": str(metric),
                "query_from": query_from_utc.isoformat(),
                "query_to": query_to_utc.isoformat(),
                "results_status": "success",
            }
        )
        return {
            "experiment_id": experiment_id,
            "metric_uuid": metric_uuid,
            "fingerprint": fingerprint,
            "metric_definition": metric,
            "query_from": query_from_utc.isoformat(),
            "query_to": query_to_utc.isoformat(),
            "result": result.model_dump(),
        }

    except Exception as e:
        query_from_utc = experiment.start_date if experiment.start_date else experiment.created_at
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
# Job and automation for timeseries calculation
# =============================================================================

experiment_timeseries_job = dagster.define_asset_job(
    name="experiment_timeseries_job",
    selection=[experiment_timeseries],
    tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
)


@dagster.sensor(
    job=experiment_timeseries_job,
    minimum_interval_seconds=30,
    tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
)
def experiment_discovery_sensor(context: dagster.SensorEvaluationContext):
    """
    Automatically discover new experiment-metric combinations and trigger timeseries calculation.

    This sensor continuously monitors for new experiments or metrics that need timeseries
    analysis. When new combinations are found, it creates dynamic partitions for the
    experiment_timeseries asset and triggers processing only for the new partitions.
    """
    try:
        current_experiment_metrics = _get_experiment_metrics(context)
        if not current_experiment_metrics:
            context.log.debug("No experiment-metrics found for timeseries analysis")
            return dagster.SkipReason("No experiments with metrics found")

        # Generate partition keys in format: experiment_{id}_metric_{uuid}_{fingerprint}
        current_partition_keys = [
            f"experiment_{exp_id}_metric_{metric_uuid}_{fingerprint}"
            for exp_id, metric_uuid, fingerprint, _ in current_experiment_metrics
        ]

        # Check which partitions are new
        existing_partitions = set(context.instance.get_dynamic_partitions(experiment_timeseries_partitions_def.name))
        new_partitions = [key for key in current_partition_keys if key not in existing_partitions]

        # Build response
        run_requests = []
        dynamic_partitions_requests = []

        if new_partitions:
            context.log.info(
                f"Discovered {len(new_partitions)} new experiment-metric combinations for timeseries analysis"
            )
            # Add new partitions
            dynamic_partitions_requests.append(experiment_timeseries_partitions_def.build_add_request(new_partitions))
            # Create run requests for new partitions only
            run_requests = [
                dagster.RunRequest(
                    run_key=f"sensor_{partition_key}_{context.cursor or 'initial'}",
                    partition_key=partition_key,
                )
                for partition_key in new_partitions
            ]
        else:
            context.log.debug("No new experiment-metrics discovered for timeseries analysis")
            return dagster.SkipReason("No new experiments to process")

        return dagster.SensorResult(
            run_requests=run_requests,
            dynamic_partitions_requests=dynamic_partitions_requests,
        )

    except Exception as e:
        context.log.exception("Failed to discover experiments")
        return dagster.SkipReason(f"Failed to discover experiments: {e}")


@dagster.schedule(
    job=experiment_timeseries_job,
    cron_schedule="0 2 * * *",  # Daily at 02:00 UTC
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
)
def daily_experiment_full_refresh_schedule(context: dagster.ScheduleEvaluationContext):
    """
    This schedule runs daily and reprocesses all known experiment-metric combinations.
    """
    try:
        existing_partitions = list(context.instance.get_dynamic_partitions(experiment_timeseries_partitions_def.name))

        if not existing_partitions:
            return dagster.SkipReason("No experiment timeseries partitions exist")

        context.log.info(f"Scheduling full refresh for {len(existing_partitions)} timeseries partitions")
        return [
            dagster.RunRequest(
                run_key=f"full_refresh_{partition_key}_{context.scheduled_execution_time.strftime('%Y%m%d')}",
                partition_key=partition_key,
            )
            for partition_key in existing_partitions
        ]

    except Exception as e:
        context.log.exception("Failed to schedule full refresh")
        return dagster.SkipReason(f"Failed to schedule full refresh: {e}")
