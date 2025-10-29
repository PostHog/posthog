"""
Dagster asset and automation for experiment regular metrics timeseries analysis.

This module defines:
- One asset (experiment_regular_metrics_timeseries) with dynamic partitions for experiment-metric combinations
- Automatic discovery and processing of new experiment-regular metric combinations
- Sensors and schedules for continuous timeseries calculation
"""

import json
from datetime import datetime, timedelta
from typing import Any, Union
from zoneinfo import ZoneInfo

from django.db.models import Q

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

# Create dynamic partitions definition for regular metric combinations
EXPERIMENT_REGULAR_METRICS_PARTITIONS_NAME = "experiment_regular_metrics"
experiment_regular_metrics_partitions_def = dagster.DynamicPartitionsDefinition(
    name=EXPERIMENT_REGULAR_METRICS_PARTITIONS_NAME
)

# =============================================================================
# Asset
# =============================================================================


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
    if not context.partition_key:
        raise dagster.Failure("This asset must be run with a partition key")

    experiment_id, metric_uuid, fingerprint = _parse_partition_key(context.partition_key)

    context.log.info(
        f"Computing timeseries results for experiment {experiment_id}, metric {metric_uuid}, fingerprint {fingerprint}"
    )

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


def _get_experiment_regular_metrics_timeseries(
    context: dagster.SensorEvaluationContext,
) -> list[tuple[int, str, str]]:
    """
    Discover active experiment-regular metric combinations from the database.

    Each combination will become a dynamic partition for the experiment_regular_metrics_timeseries asset.

    Args:
        context: Dagster context for logging to UI.

    Returns:
        List of tuples containing (experiment_id, metric_uuid, fingerprint)
        for all valid experiment-regular metric combinations that should be processed.
    """
    experiment_metrics = []

    # Query experiments that are eligible for timeseries analysis (running experiments only)
    # Exclude experiments running for longer than 3 months to avoid continuously recalculating
    # likely stale experiments. Users can still manually backfill those.
    experiments = Experiment.objects.filter(
        deleted=False,
        stats_config__timeseries=True,
        start_date__isnull=False,
        start_date__gte=datetime.now(ZoneInfo("UTC")) - timedelta(days=90),
        end_date__isnull=True,
    ).exclude(
        # Exclude if both metrics and metrics_secondary are empty or null
        Q(metrics__isnull=True) | Q(metrics=[]),
        Q(metrics_secondary__isnull=True) | Q(metrics_secondary=[]),
    )

    for experiment in experiments:
        all_metrics = (experiment.metrics or []) + (experiment.metrics_secondary or [])

        for metric in all_metrics:
            metric_uuid = metric.get("uuid")
            if not metric_uuid:
                context.log.warning(f"Metric in experiment {experiment.id} has no UUID, skipping")
                continue

            fingerprint = compute_metric_fingerprint(
                metric,
                experiment.start_date,
                get_experiment_stats_method(experiment),
                experiment.exposure_criteria,
            )

            experiment_metrics.append((experiment.id, metric_uuid, fingerprint))

    return experiment_metrics


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
    return refresh_experiment_metric_partitions(
        context=context,
        partition_name=EXPERIMENT_REGULAR_METRICS_PARTITIONS_NAME,
        partitions_def=experiment_regular_metrics_partitions_def,
        get_metrics_fn=_get_experiment_regular_metrics_timeseries,
    )


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
    return schedule_experiment_metric_partitions(
        context=context,
        partition_name=EXPERIMENT_REGULAR_METRICS_PARTITIONS_NAME,
    )
