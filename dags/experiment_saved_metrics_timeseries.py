"""
Dagster asset and automation for experiment saved metrics timeseries analysis.

This module defines:
- One asset (experiment_saved_metrics_timeseries) with dynamic partitions for experiment-saved metric combinations
- Automatic discovery and processing of new experiment-saved metric combinations
- Sensors and schedules for continuous timeseries calculation
"""

import json
from datetime import datetime, timedelta
from typing import Any, Union
from zoneinfo import ZoneInfo

import dagster

from posthog.schema import ExperimentFunnelMetric, ExperimentMeanMetric, ExperimentQuery, ExperimentRatioMetric

from posthog.hogql_queries.experiments.experiment_metric_fingerprint import compute_metric_fingerprint
from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.hogql_queries.experiments.utils import get_experiment_stats_method
from posthog.models.experiment import Experiment, ExperimentMetricResult

from dags.common import JobOwners
from dags.experiments import (
    _parse_partition_key,
    refresh_experiment_metric_partitions,
    remove_step_sessions_from_experiment_result,
    schedule_experiment_metric_partitions,
)

# =============================================================================
# Dynamic Partitions Setup
# =============================================================================

# Create dynamic partitions definition for saved metric combinations
EXPERIMENT_SAVED_METRICS_PARTITIONS_NAME = "experiment_saved_metrics"
experiment_saved_metrics_partitions_def = dagster.DynamicPartitionsDefinition(
    name=EXPERIMENT_SAVED_METRICS_PARTITIONS_NAME
)

# =============================================================================
# Asset
# =============================================================================


@dagster.asset(
    partitions_def=experiment_saved_metrics_partitions_def,
    group_name="experiments",
    tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
)
def experiment_saved_metrics_timeseries(context: dagster.AssetExecutionContext) -> dict[str, Any]:
    """
    Calculate timeseries analysis results for a specific experiment-saved metric combination.

    This is a single asset with dynamic partitions - one partition per experiment-saved metric
    combination. Each partition computes timeseries analysis for one saved metric from one
    experiment using ExperimentQueryRunner.
    """
    # Parse partition key to get experiment and saved metric info
    if not context.partition_key:
        raise dagster.Failure("This asset must be run with a partition key")

    experiment_id, metric_uuid, fingerprint = _parse_partition_key(context.partition_key)

    context.log.info(
        f"Computing timeseries results for experiment {experiment_id}, metric {metric_uuid}, fingerprint {fingerprint}"
    )

    try:
        experiment = Experiment.objects.get(id=experiment_id, deleted=False)

        saved_metric = None
        for exp_to_sm in experiment.experimenttosavedmetric_set.select_related("saved_metric").all():
            if exp_to_sm.saved_metric.query.get("uuid") == metric_uuid:
                saved_metric = exp_to_sm.saved_metric
                break

        if not saved_metric:
            raise dagster.Failure(f"No saved metric with UUID {metric_uuid} found for experiment {experiment_id}")

    except Experiment.DoesNotExist:
        raise dagster.Failure(f"Experiment {experiment_id} not found or deleted")

    query = saved_metric.query
    if query.get("kind") != "ExperimentMetric":
        raise dagster.Failure(f"Unexpected saved metric query kind: {query.get('kind')}. Expected 'ExperimentMetric'")

    metric_type = query.get("metric_type")
    metric_obj: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]
    if metric_type == "mean":
        metric_obj = ExperimentMeanMetric(**query)
    elif metric_type == "funnel":
        metric_obj = ExperimentFunnelMetric(**query)
    elif metric_type == "ratio":
        metric_obj = ExperimentRatioMetric(**query)
    else:
        raise dagster.Failure(f"Unknown metric type: {metric_type}")

    try:
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

        result = remove_step_sessions_from_experiment_result(result)

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
                "saved_metric_id": saved_metric.id,
                "saved_metric_uuid": saved_metric.query.get("uuid"),
                "saved_metric_name": saved_metric.name,
                "fingerprint": fingerprint,
                "metric_type": metric_type,
                "experiment_name": experiment.name,
                "experiment_start_date": experiment.start_date.isoformat() if experiment.start_date else None,
                "experiment_exposure_criteria": json.dumps(experiment.exposure_criteria)
                if experiment.exposure_criteria
                else None,
                "query_from": query_from_utc.isoformat(),
                "query_to": query_to_utc.isoformat(),
                "results_status": "success",
            }
        )
        return {
            "experiment_id": experiment_id,
            "saved_metric_id": saved_metric.id,
            "saved_metric_uuid": saved_metric.query.get("uuid"),
            "saved_metric_name": saved_metric.name,
            "fingerprint": fingerprint,
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
# Job and automation for saved metrics timeseries calculation
# =============================================================================


def _get_experiment_saved_metrics_timeseries(context: dagster.SensorEvaluationContext) -> list[tuple[int, str, str]]:
    """
    Discover active experiment-saved metric combinations from the database.

    Each combination will become a dynamic partition for the experiment_saved_metrics_timeseries asset.

    Args:
        context: Dagster context for logging to UI.

    Returns:
        List of tuples containing (experiment_id, metric_uuid, fingerprint)
        for all valid experiment-saved metric combinations that should be processed.
    """
    experiment_saved_metrics = []

    # Query experiments that are eligible for timeseries analysis (running experiments only)
    # Exclude experiments running for longer than 3 months to avoid continuously recalculating
    # likely stale experiments. Users can still manually backfill those.
    experiments = Experiment.objects.filter(
        deleted=False,
        stats_config__timeseries=True,
        start_date__isnull=False,
        start_date__gte=datetime.now(ZoneInfo("UTC")) - timedelta(days=90),
        end_date__isnull=True,
    ).prefetch_related("experimenttosavedmetric_set__saved_metric")

    for experiment in experiments:
        # Get all saved metrics linked to this experiment
        for exp_to_saved_metric in experiment.experimenttosavedmetric_set.all():
            saved_metric = exp_to_saved_metric.saved_metric

            fingerprint = compute_metric_fingerprint(
                saved_metric.query,
                experiment.start_date,
                get_experiment_stats_method(experiment),
                experiment.exposure_criteria,
            )

            metric_uuid = saved_metric.query.get("uuid")
            if not metric_uuid:
                context.log.warning(f"Saved metric {saved_metric.id} has no UUID in query, skipping")
                continue

            experiment_saved_metrics.append((experiment.id, metric_uuid, fingerprint))

    return experiment_saved_metrics


experiment_saved_metrics_timeseries_job = dagster.define_asset_job(
    name="experiment_saved_metrics_timeseries_job",
    selection=[experiment_saved_metrics_timeseries],
    tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
)


@dagster.sensor(
    job=experiment_saved_metrics_timeseries_job,
    minimum_interval_seconds=30,
    tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
)
def experiment_saved_metrics_timeseries_discovery_sensor(context: dagster.SensorEvaluationContext):
    """
    Automatically discover new experiment-saved metric combinations and trigger timeseries calculation.

    This sensor continuously monitors for new experiments or saved metrics that need timeseries
    analysis. When new combinations are found, it creates dynamic partitions for the
    experiment_saved_metrics_timeseries asset and triggers processing only for the new partitions.
    """
    return refresh_experiment_metric_partitions(
        context=context,
        partition_name=EXPERIMENT_SAVED_METRICS_PARTITIONS_NAME,
        partitions_def=experiment_saved_metrics_partitions_def,
        get_metrics_fn=_get_experiment_saved_metrics_timeseries,
    )


@dagster.schedule(
    job=experiment_saved_metrics_timeseries_job,
    cron_schedule="0 * * * *",  # Every hour at minute 0
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_EXPERIMENTS.value},
)
def experiment_saved_metrics_timeseries_refresh_schedule(context: dagster.ScheduleEvaluationContext):
    """
    This schedule runs hourly and reprocesses experiment-saved metric combinations
    for teams scheduled at the current hour.
    """
    return schedule_experiment_metric_partitions(
        context=context,
        partition_name=EXPERIMENT_SAVED_METRICS_PARTITIONS_NAME,
    )
