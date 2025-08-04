"""
Dagster asset and automation for experiment timeseries analysis.

This module defines:
- One asset (experiment_timeseries) with dynamic partitions for experiment-metric combinations
- Automatic discovery and processing of new experiment-metric combinations
- Sensors and schedules for continuous timeseries calculation
"""

import dagster
from typing import Any
from posthog.models.experiment import Experiment
from dags.common import JobOwners
from datetime import datetime, UTC

# =============================================================================
# Dynamic Partitions Setup
# =============================================================================

# Create dynamic partitions definition for experiment-metric combinations
experiment_timeseries_partitions_def = dagster.DynamicPartitionsDefinition(name="experiment_timeseries")

# =============================================================================
# Asset
# =============================================================================


def _get_experiment_metrics() -> list[tuple[int, str, dict[str, Any]]]:
    """
    Discover active experiment-metric combinations from the database.

    Each combination will become a dynamic partition for the experiment_timeseries asset.

    Returns:
        List of tuples containing (experiment_id, metric_uuid, metric_dict)
        for all valid experiment-metric combinations that should be processed.
    """
    experiment_metrics = []

    # Query experiments that are eligible for timeseries analysis (running experiments only)
    experiments = Experiment.objects.filter(
        deleted=False,
        metrics__isnull=False,
        stats_config__timeseries=True,
        start_date__isnull=False,
        end_date__isnull=True,
    ).exclude(metrics=[])

    for experiment in experiments:
        metrics = experiment.metrics or []

        for metric in metrics:
            metric_uuid = metric.get("uuid")
            if not metric_uuid:
                continue
            experiment_metrics.append((experiment.id, metric_uuid, metric))

    return experiment_metrics


def _parse_partition_key(partition_key: str) -> tuple[int, str]:
    """
    Parse partition key to extract experiment ID and metric UUID.

    The partition key format is: experiment_{id}_metric_{uuid}
    """
    parts = partition_key.split("_")
    if len(parts) != 4 or parts[0] != "experiment" or parts[2] != "metric":
        raise ValueError(f"Invalid partition key format: {partition_key}")

    try:
        experiment_id = int(parts[1])
        metric_uuid = parts[3]
        return experiment_id, metric_uuid
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
    experiment (currently a placeholder - will be replaced with actual statistical analysis).

    Returns:
        Dictionary containing experiment metadata, metric definition, and timeseries results.
    """
    # Parse partition key to get experiment and metric info
    if not context.partition_key:
        raise dagster.Failure("This asset must be run with a partition key")

    experiment_id, metric_uuid = _parse_partition_key(context.partition_key)

    context.log.info(f"Computing timeseries results for experiment {experiment_id}, metric {metric_uuid}")

    # Load experiment and metric configuration from database
    try:
        experiment = Experiment.objects.get(id=experiment_id, deleted=False)
        if not experiment.metrics or metric_uuid not in [m.get("uuid") for m in experiment.metrics]:
            raise dagster.Failure(f"Metric UUID {metric_uuid} not found for experiment {experiment_id}")

        metric = next(m for m in experiment.metrics if m.get("uuid") == metric_uuid)

    except Experiment.DoesNotExist:
        raise dagster.Failure(f"Experiment {experiment_id} not found or deleted")

    # TODO: Replace this placeholder with actual timeseries analysis logic
    placeholder_results = {
        "placeholder": True,
        "message": "Timeseries calculation logic to be implemented",
        "metric_name": metric.get("name", f"Metric {metric_uuid}"),
    }

    # Add metadata for Dagster UI display
    context.add_output_metadata(
        metadata={
            "experiment_id": experiment_id,
            "metric_uuid": metric_uuid,
            "metric_type": metric.get("kind"),
            "metric_name": metric.get("name", f"Metric {metric_uuid}"),
            "experiment_name": experiment.name,
            "metric_definition": str(metric),
            "computed_at": datetime.now(UTC).isoformat(),
            "results_status": "placeholder",
            "results_message": placeholder_results["message"],
        }
    )

    results = {
        "experiment_id": experiment_id,
        "metric_uuid": metric_uuid,
        "metric_definition": metric,
        "results": placeholder_results,
        "computed_at": datetime.now(UTC).isoformat(),
    }

    return results


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
        current_experiment_metrics = _get_experiment_metrics()
        if not current_experiment_metrics:
            context.log.debug("No experiment-metrics found for timeseries analysis")
            return dagster.SkipReason("No experiments with metrics found")

        # Generate partition keys in format: experiment_{id}_metric_{uuid}
        current_partition_keys = [
            f"experiment_{exp_id}_metric_{metric_uuid}" for exp_id, metric_uuid, _ in current_experiment_metrics
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
