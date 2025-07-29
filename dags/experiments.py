"""
EXPERIMENTS DAGSTER ASSETS
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
experiment_partitions_def = dagster.DynamicPartitionsDefinition(name="experiment_metrics")

# =============================================================================
# Assets
# =============================================================================


def _get_experiment_metrics() -> list[tuple[int, str, dict[str, Any]]]:
    """
    Discover all experiment-metric combinations that need Dagster assets
    """
    experiment_metrics = []

    # Query experiments that are eligible
    experiments = Experiment.objects.filter(
        deleted=False,
        metrics__isnull=False,
        stats_config__timeseries="true",
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
    partitions_def=experiment_partitions_def,
    group_name="experiments",
    tags={"owner": JobOwners.TEAM_EXPERIMENTS.value}
)
def experiment_metrics(context: dagster.AssetExecutionContext) -> dict[str, Any]:
    """
    Compute timeseries results for experiment-metric combinations.
    """
    # Parse partition key to get experiment and metric info
    if not context.partition_key:
        raise dagster.Failure("This asset must be run with a partition key")
    
    experiment_id, metric_uuid = _parse_partition_key(context.partition_key)
    
    context.log.info(f"Computing results for experiment {experiment_id}, metric {metric_uuid}")
    
    # Load experiment and metric from database
    try:
        experiment = Experiment.objects.get(id=experiment_id, deleted=False)
        if not experiment.metrics or metric_uuid not in [m.get("uuid") for m in experiment.metrics]:
            raise dagster.Failure(
                f"Metric UUID {metric_uuid} not found for experiment {experiment_id}"
            )
        
        metric = next(m for m in experiment.metrics if m.get("uuid") == metric_uuid)
        
    except Experiment.DoesNotExist:
        raise dagster.Failure(f"Experiment {experiment_id} not found or deleted")
    
    # TODO: Replace this placeholder with actual experiment analysis logic
    placeholder_results = {
        "placeholder": True,
        "message": "Calculation logic to be implemented",
        "metric_name": metric.get("name", f"Metric {metric_uuid}"),
    }
    
    # Add all metadata at once
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
# Jobs and sensors (replacing the schedule approach)
# =============================================================================

experiment_computation_job = dagster.define_asset_job(
    name="experiment_computation_job",
    selection=[experiment_metrics],
    tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
)

@dagster.sensor(
    job=experiment_computation_job,
    minimum_interval_seconds=60,  # Check every minute
    tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
)
def experiment_discovery_sensor(context: dagster.SensorEvaluationContext):
    """
    Automatically discover experiments and manage dynamic partitions.
    
    This sensor:
    1. Discovers current experiment-metric combinations from database
    2. Automatically adds missing partitions
    3. Triggers runs for all current partitions
    """
    try:
        current_experiment_metrics = _get_experiment_metrics()
        if not current_experiment_metrics:
            context.log.debug("No experiment-metrics found")
            return dagster.SkipReason("No experiments with metrics found")
        
        # Generate partition keys for current experiments
        current_partition_keys = [
            f"experiment_{exp_id}_metric_{metric_uuid}" 
            for exp_id, metric_uuid, _ in current_experiment_metrics
        ]
        
        # Check which partitions are new
        existing_partitions = set(context.instance.get_dynamic_partitions(experiment_partitions_def.name))
        new_partitions = [key for key in current_partition_keys if key not in existing_partitions]
        
        # Build response
        run_requests = []
        dynamic_partitions_requests = []
        
        if new_partitions:
            context.log.info(f"Discovered {len(new_partitions)} new experiment-metric combinations")
            # Add new partitions
            dynamic_partitions_requests.append(
                experiment_partitions_def.build_add_request(new_partitions)
            )
            # Create run requests for new partitions only
            run_requests = [
                dagster.RunRequest(
                    run_key=f"sensor_{partition_key}_{context.sensor_tick.id}",
                    partition_key=partition_key,
                )
                for partition_key in new_partitions
            ]
        else:
            context.log.debug("No new experiment-metrics discovered")
            return dagster.SkipReason("No new experiments to process")
        
        return dagster.SensorResult(
            run_requests=run_requests,
            dynamic_partitions_requests=dynamic_partitions_requests,
        )
        
    except Exception as e:
        context.log.error(f"Failed to discover experiments: {e}")
        return dagster.SkipReason(f"Failed to discover experiments: {e}")

# Optional: Keep a simple schedule for periodic full processing
@dagster.schedule(
    job=experiment_computation_job,
    cron_schedule="0 2 * * *",  # Daily at 2 AM UTC
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
)
def daily_experiment_full_refresh_schedule(context: dagster.ScheduleEvaluationContext):
    """
    Optional: Process all existing partitions daily for full refresh.
    """
    try:
        existing_partitions = list(context.instance.get_dynamic_partitions(experiment_partitions_def.name))
        
        if not existing_partitions:
            return dagster.SkipReason("No experiment partitions exist")
        
        context.log.info(f"Scheduling full refresh for {len(existing_partitions)} partitions")
        return [
            dagster.RunRequest(
                run_key=f"full_refresh_{partition_key}_{context.scheduled_execution_time.strftime('%Y%m%d')}",
                partition_key=partition_key,
            )
            for partition_key in existing_partitions
        ]
        
    except Exception as e:
        context.log.error(f"Failed to schedule full refresh: {e}")
        return dagster.SkipReason(f"Failed to schedule full refresh: {e}")
