from datetime import datetime, timedelta
from typing import Union
from zoneinfo import ZoneInfo

from django.db import close_old_connections
from django.db.models import Q

import structlog
import temporalio.activity

from posthog.schema import ExperimentFunnelMetric, ExperimentMeanMetric, ExperimentQuery, ExperimentRatioMetric

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.experiments.experiment_metric_fingerprint import compute_metric_fingerprint
from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.hogql_queries.experiments.utils import get_experiment_stats_method
from posthog.models.experiment import (
    Experiment,
    ExperimentMetricResult as ExperimentMetricResultModel,
)
from posthog.sync import database_sync_to_async
from posthog.temporal.experiments.models import (
    ExperimentRegularMetricInput,
    ExperimentRegularMetricResult,
    ExperimentSavedMetricInput,
    ExperimentSavedMetricResult,
)
from posthog.temporal.experiments.utils import (
    DEFAULT_EXPERIMENT_RECALCULATION_HOUR,
    remove_step_sessions_from_experiment_result,
)

from products.experiments.stats.shared.statistics import StatisticError

logger = structlog.get_logger(__name__)


@database_sync_to_async
def _get_experiment_regular_metrics_for_hour_sync(hour: int) -> list[ExperimentRegularMetricInput]:
    close_old_connections()

    experiment_metrics: list[ExperimentRegularMetricInput] = []

    # Build time filter - teams with NULL recalculation_time default to hour 2 (02:00 UTC)
    if hour == DEFAULT_EXPERIMENT_RECALCULATION_HOUR:
        time_filter = Q(team__experiment_recalculation_time__hour=hour) | Q(
            team__experiment_recalculation_time__isnull=True
        )
    else:
        time_filter = Q(team__experiment_recalculation_time__hour=hour)

    experiments = Experiment.objects.filter(
        time_filter,
        deleted=False,
        scheduling_config__timeseries=True,
        start_date__isnull=False,
        start_date__gte=datetime.now(ZoneInfo("UTC")) - timedelta(days=30),
        end_date__isnull=True,
    ).exclude(
        Q(metrics__isnull=True) | Q(metrics=[]),
        Q(metrics_secondary__isnull=True) | Q(metrics_secondary=[]),
    )

    for experiment in experiments:
        all_metrics = (experiment.metrics or []) + (experiment.metrics_secondary or [])

        for metric in all_metrics:
            metric_uuid = metric.get("uuid")
            if not metric_uuid:
                logger.warning(
                    "Metric has no UUID, skipping",
                    experiment_id=experiment.id,
                )
                continue

            fingerprint = compute_metric_fingerprint(
                metric,
                experiment.start_date,
                get_experiment_stats_method(experiment),
                experiment.exposure_criteria,
            )

            experiment_metrics.append(
                ExperimentRegularMetricInput(
                    experiment_id=experiment.id,
                    metric_uuid=metric_uuid,
                    fingerprint=fingerprint,
                )
            )

    logger.info(
        "Discovered experiment metrics for hour",
        hour=hour,
        count=len(experiment_metrics),
    )

    return experiment_metrics


@temporalio.activity.defn
async def get_experiment_regular_metrics_for_hour(hour: int) -> list[ExperimentRegularMetricInput]:
    """Discover experiment-metrics that need calculation for teams scheduled at this hour."""
    return await _get_experiment_regular_metrics_for_hour_sync(hour)


@database_sync_to_async
def _calculate_experiment_regular_metric_sync(
    experiment_id: int,
    metric_uuid: str,
    fingerprint: str,
) -> ExperimentRegularMetricResult:
    close_old_connections()

    logger.info(
        "Calculating experiment metric",
        experiment_id=experiment_id,
        metric_uuid=metric_uuid,
        fingerprint=fingerprint,
    )

    try:
        experiment = Experiment.objects.get(id=experiment_id, deleted=False)
    except Experiment.DoesNotExist:
        return ExperimentRegularMetricResult(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            success=False,
            error_message=f"Experiment {experiment_id} not found or deleted",
        )

    all_metrics = (experiment.metrics or []) + (experiment.metrics_secondary or [])
    metric_dict = None
    for metric in all_metrics:
        if metric.get("uuid") == metric_uuid:
            metric_dict = metric
            break

    if not metric_dict:
        return ExperimentRegularMetricResult(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            success=False,
            error_message=f"Metric {metric_uuid} not found in experiment {experiment_id}",
        )

    metric_type = metric_dict.get("metric_type")
    metric_obj: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]
    if metric_type == "mean":
        metric_obj = ExperimentMeanMetric(**metric_dict)
    elif metric_type == "funnel":
        metric_obj = ExperimentFunnelMetric(**metric_dict)
    elif metric_type == "ratio":
        metric_obj = ExperimentRatioMetric(**metric_dict)
    else:
        return ExperimentRegularMetricResult(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            success=False,
            error_message=f"Unknown metric type: {metric_type}",
        )

    if not experiment.start_date:
        return ExperimentRegularMetricResult(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            success=False,
            error_message=f"Experiment {experiment_id} has no start_date",
        )

    query_from_utc = experiment.start_date
    query_to_utc = datetime.now(ZoneInfo("UTC"))

    try:
        experiment_query = ExperimentQuery(
            experiment_id=experiment_id,
            metric=metric_obj,
        )

        query_runner = ExperimentQueryRunner(
            query=experiment_query,
            team=experiment.team,
            workload=Workload.OFFLINE,
        )
        result = query_runner._calculate()
        result = remove_step_sessions_from_experiment_result(result)
        result_dict = result.model_dump()

        completed_at = datetime.now(ZoneInfo("UTC"))

        ExperimentMetricResultModel.objects.update_or_create(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            query_to=query_to_utc,
            defaults={
                "query_from": query_from_utc,
                "status": ExperimentMetricResultModel.Status.COMPLETED,
                "result": result_dict,
                "query_id": None,
                "completed_at": completed_at,
                "error_message": None,
            },
        )

        logger.info(
            "Successfully calculated experiment metric",
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
        )

        return ExperimentRegularMetricResult(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            success=True,
        )

    except (StatisticError, ZeroDivisionError) as e:
        ExperimentMetricResultModel.objects.update_or_create(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            query_to=query_to_utc,
            defaults={
                "query_from": query_from_utc,
                "status": ExperimentMetricResultModel.Status.FAILED,
                "result": None,
                "query_id": None,
                "completed_at": None,
                "error_message": str(e),
            },
        )

        logger.warning(
            "Experiment metric calculation failed due to insufficient data",
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            error=str(e),
        )

        return ExperimentRegularMetricResult(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            success=False,
            error_message=str(e),
        )

    except Exception as e:
        ExperimentMetricResultModel.objects.update_or_create(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            query_to=query_to_utc,
            defaults={
                "query_from": query_from_utc,
                "status": ExperimentMetricResultModel.Status.FAILED,
                "result": None,
                "query_id": None,
                "completed_at": None,
                "error_message": str(e),
            },
        )

        logger.exception(
            "Experiment metric calculation failed",
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
        )

        raise


@temporalio.activity.defn
async def calculate_experiment_regular_metric(
    experiment_id: int,
    metric_uuid: str,
    fingerprint: str,
) -> ExperimentRegularMetricResult:
    """Calculate timeseries results for a single experiment-metric combination."""
    return await _calculate_experiment_regular_metric_sync(experiment_id, metric_uuid, fingerprint)


@database_sync_to_async
def _get_experiment_saved_metrics_for_hour_sync(hour: int) -> list[ExperimentSavedMetricInput]:
    close_old_connections()

    experiment_metrics: list[ExperimentSavedMetricInput] = []

    if hour == DEFAULT_EXPERIMENT_RECALCULATION_HOUR:
        time_filter = Q(team__experiment_recalculation_time__hour=hour) | Q(
            team__experiment_recalculation_time__isnull=True
        )
    else:
        time_filter = Q(team__experiment_recalculation_time__hour=hour)

    experiments = Experiment.objects.filter(
        time_filter,
        deleted=False,
        scheduling_config__timeseries=True,
        start_date__isnull=False,
        start_date__gte=datetime.now(ZoneInfo("UTC")) - timedelta(days=30),
        end_date__isnull=True,
    ).prefetch_related("experimenttosavedmetric_set__saved_metric")

    for experiment in experiments:
        for exp_to_saved_metric in experiment.experimenttosavedmetric_set.all():
            saved_metric = exp_to_saved_metric.saved_metric
            metric_uuid = saved_metric.query.get("uuid")

            if not metric_uuid:
                logger.warning(
                    "Saved metric has no UUID, skipping",
                    experiment_id=experiment.id,
                    saved_metric_id=saved_metric.id,
                )
                continue

            fingerprint = compute_metric_fingerprint(
                saved_metric.query,
                experiment.start_date,
                get_experiment_stats_method(experiment),
                experiment.exposure_criteria,
            )

            experiment_metrics.append(
                ExperimentSavedMetricInput(
                    experiment_id=experiment.id,
                    metric_uuid=metric_uuid,
                    fingerprint=fingerprint,
                )
            )

    logger.info(
        "Discovered experiment saved metrics for hour",
        hour=hour,
        count=len(experiment_metrics),
    )

    return experiment_metrics


@temporalio.activity.defn
async def get_experiment_saved_metrics_for_hour(hour: int) -> list[ExperimentSavedMetricInput]:
    """Discover experiment-saved metrics that need calculation for teams scheduled at this hour."""
    return await _get_experiment_saved_metrics_for_hour_sync(hour)


@database_sync_to_async
def _calculate_experiment_saved_metric_sync(
    experiment_id: int,
    metric_uuid: str,
    fingerprint: str,
) -> ExperimentSavedMetricResult:
    close_old_connections()

    logger.info(
        "Calculating experiment saved metric",
        experiment_id=experiment_id,
        metric_uuid=metric_uuid,
        fingerprint=fingerprint,
    )

    try:
        experiment = Experiment.objects.get(id=experiment_id, deleted=False)
    except Experiment.DoesNotExist:
        return ExperimentSavedMetricResult(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            success=False,
            error_message=f"Experiment {experiment_id} not found or deleted",
        )

    saved_metric = None
    for exp_to_sm in experiment.experimenttosavedmetric_set.select_related("saved_metric").all():
        if exp_to_sm.saved_metric.query.get("uuid") == metric_uuid:
            saved_metric = exp_to_sm.saved_metric
            break

    if not saved_metric:
        return ExperimentSavedMetricResult(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            success=False,
            error_message=f"Saved metric {metric_uuid} not found for experiment {experiment_id}",
        )

    query = saved_metric.query
    metric_type = query.get("metric_type")
    metric_obj: Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]
    if metric_type == "mean":
        metric_obj = ExperimentMeanMetric(**query)
    elif metric_type == "funnel":
        metric_obj = ExperimentFunnelMetric(**query)
    elif metric_type == "ratio":
        metric_obj = ExperimentRatioMetric(**query)
    else:
        return ExperimentSavedMetricResult(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            success=False,
            error_message=f"Unknown metric type: {metric_type}",
        )

    if not experiment.start_date:
        return ExperimentSavedMetricResult(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            success=False,
            error_message=f"Experiment {experiment_id} has no start_date",
        )

    query_from_utc = experiment.start_date
    query_to_utc = datetime.now(ZoneInfo("UTC"))

    try:
        experiment_query = ExperimentQuery(
            experiment_id=experiment_id,
            metric=metric_obj,
        )

        query_runner = ExperimentQueryRunner(
            query=experiment_query,
            team=experiment.team,
            workload=Workload.OFFLINE,
        )
        result = query_runner._calculate()
        result = remove_step_sessions_from_experiment_result(result)
        result_dict = result.model_dump()

        completed_at = datetime.now(ZoneInfo("UTC"))

        ExperimentMetricResultModel.objects.update_or_create(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            query_to=query_to_utc,
            defaults={
                "query_from": query_from_utc,
                "status": ExperimentMetricResultModel.Status.COMPLETED,
                "result": result_dict,
                "query_id": None,
                "completed_at": completed_at,
                "error_message": None,
            },
        )

        logger.info(
            "Successfully calculated experiment saved metric",
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
        )

        return ExperimentSavedMetricResult(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            success=True,
        )

    except (StatisticError, ZeroDivisionError) as e:
        ExperimentMetricResultModel.objects.update_or_create(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            query_to=query_to_utc,
            defaults={
                "query_from": query_from_utc,
                "status": ExperimentMetricResultModel.Status.FAILED,
                "result": None,
                "query_id": None,
                "completed_at": None,
                "error_message": str(e),
            },
        )

        logger.warning(
            "Experiment saved metric calculation failed due to insufficient data",
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            error=str(e),
        )

        return ExperimentSavedMetricResult(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            success=False,
            error_message=str(e),
        )

    except Exception as e:
        ExperimentMetricResultModel.objects.update_or_create(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            query_to=query_to_utc,
            defaults={
                "query_from": query_from_utc,
                "status": ExperimentMetricResultModel.Status.FAILED,
                "result": None,
                "query_id": None,
                "completed_at": None,
                "error_message": str(e),
            },
        )

        logger.exception(
            "Experiment saved metric calculation failed",
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
        )

        raise


@temporalio.activity.defn
async def calculate_experiment_saved_metric(
    experiment_id: int,
    metric_uuid: str,
    fingerprint: str,
) -> ExperimentSavedMetricResult:
    """Calculate timeseries results for a single experiment-saved metric combination."""
    return await _calculate_experiment_saved_metric_sync(experiment_id, metric_uuid, fingerprint)
