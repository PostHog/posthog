from datetime import datetime, time, timedelta
from typing import Any, Union
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
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.experiments.models import (
    ExperimentRegularMetricInput,
    ExperimentRegularMetricResult,
    ExperimentSavedMetricInput,
    ExperimentSavedMetricResult,
)
from posthog.temporal.experiments.utils import (
    DEFAULT_EXPERIMENT_RECALCULATION_HOUR,
    check_significance_transition,
    get_metric,
)

from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult as ExperimentMetricResultModel,
    ExperimentTimeseriesRecalculation,
)
from products.experiments.stats.shared.statistics import StatisticError

logger = structlog.get_logger(__name__)


@database_sync_to_async
def _get_experiment_regular_metrics_for_hour_sync(hour: int) -> list[ExperimentRegularMetricInput]:
    close_old_connections()

    experiment_metrics: list[ExperimentRegularMetricInput] = []

    # Build time filter - teams with NULL recalculation_time default to hour 2 (02:00 UTC)
    # The filter traverses Experiment -> Team -> TeamExperimentsConfig via Django's reverse relation
    if hour == DEFAULT_EXPERIMENT_RECALCULATION_HOUR:
        time_filter = (
            Q(team__teamexperimentsconfig__experiment_recalculation_time__hour=hour)
            | Q(team__teamexperimentsconfig__experiment_recalculation_time__isnull=True)
            | Q(team__teamexperimentsconfig__isnull=True)
        )
    else:
        time_filter = Q(team__teamexperimentsconfig__experiment_recalculation_time__hour=hour)

    experiments = Experiment.objects.filter(
        time_filter,
        deleted=False,
        status=Experiment.Status.RUNNING,
        start_date__gte=datetime.now(ZoneInfo("UTC")) - timedelta(days=30),
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
                only_count_matured_users=experiment.only_count_matured_users,
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

        check_significance_transition(experiment, metric_uuid, fingerprint, result_dict, query_to_utc)

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
        time_filter = (
            Q(team__teamexperimentsconfig__experiment_recalculation_time__hour=hour)
            | Q(team__teamexperimentsconfig__experiment_recalculation_time__isnull=True)
            | Q(team__teamexperimentsconfig__isnull=True)
        )
    else:
        time_filter = Q(team__teamexperimentsconfig__experiment_recalculation_time__hour=hour)

    experiments = Experiment.objects.filter(
        time_filter,
        deleted=False,
        status=Experiment.Status.RUNNING,
        start_date__gte=datetime.now(ZoneInfo("UTC")) - timedelta(days=30),
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
                only_count_matured_users=experiment.only_count_matured_users,
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

        check_significance_transition(experiment, metric_uuid, fingerprint, result_dict, query_to_utc)

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


def _backfill_experiment_metric_sync(recalculation_id: str) -> dict[str, Any]:
    close_old_connections()

    logger.info("Starting timeseries recalculation", recalculation_id=recalculation_id)

    try:
        recalculation_request = ExperimentTimeseriesRecalculation.objects.get(id=recalculation_id)
    except ExperimentTimeseriesRecalculation.DoesNotExist:
        raise ValueError(f"Recalculation request {recalculation_id} not found")

    if recalculation_request.status in (
        ExperimentTimeseriesRecalculation.Status.PENDING,
        ExperimentTimeseriesRecalculation.Status.FAILED,
    ):
        recalculation_request.status = ExperimentTimeseriesRecalculation.Status.IN_PROGRESS
        recalculation_request.save(update_fields=["status"])

    experiment = recalculation_request.experiment
    if not experiment.start_date:
        raise ValueError(f"Experiment {experiment.id} has no start_date")

    team_tz = ZoneInfo(experiment.team.timezone) if experiment.team.timezone else ZoneInfo("UTC")
    start_date = experiment.start_date.astimezone(team_tz).date()

    if experiment.end_date:
        end_date = experiment.end_date.astimezone(team_tz).date()
    else:
        end_date = datetime.now(team_tz).date()

    if recalculation_request.last_successful_date:
        current_date = recalculation_request.last_successful_date + timedelta(days=1)
        logger.info("Resuming recalculation", current_date=str(current_date))
    else:
        current_date = start_date
        logger.info("Starting fresh recalculation", current_date=str(current_date))

    metric_obj = get_metric(recalculation_request.metric)
    experiment_query = ExperimentQuery(experiment_id=experiment.id, metric=metric_obj)
    fingerprint = recalculation_request.fingerprint

    days_processed = 0

    with HeartbeaterSync(logger=logger):
        while current_date <= end_date:
            try:
                end_of_day_team_tz = datetime.combine(current_date + timedelta(days=1), time(0, 0, 0)).replace(
                    tzinfo=team_tz
                )
                query_to_utc = end_of_day_team_tz.astimezone(ZoneInfo("UTC"))

                query_runner = ExperimentQueryRunner(
                    query=experiment_query,
                    team=experiment.team,
                    override_end_date=query_to_utc,
                    workload=Workload.OFFLINE,
                )
                result = query_runner._calculate()

                ExperimentMetricResultModel.objects.update_or_create(
                    experiment_id=experiment.id,
                    metric_uuid=recalculation_request.metric["uuid"],
                    query_to=query_to_utc,
                    defaults={
                        "fingerprint": fingerprint,
                        "query_from": experiment.start_date,
                        "status": ExperimentMetricResultModel.Status.COMPLETED,
                        "result": result.model_dump(),
                        "query_id": None,
                        "completed_at": datetime.now(ZoneInfo("UTC")),
                        "error_message": None,
                    },
                )

                recalculation_request.last_successful_date = current_date
                recalculation_request.save(update_fields=["last_successful_date"])
                days_processed += 1

            except Exception:
                logger.exception(
                    "Timeseries recalculation failed",
                    recalculation_id=recalculation_id,
                    failed_date=str(current_date),
                )
                recalculation_request.status = ExperimentTimeseriesRecalculation.Status.FAILED
                recalculation_request.save(update_fields=["status"])
                raise

            current_date += timedelta(days=1)

    recalculation_request.status = ExperimentTimeseriesRecalculation.Status.COMPLETED
    recalculation_request.save(update_fields=["status"])

    logger.info(
        "Timeseries recalculation completed",
        recalculation_id=recalculation_id,
        days_processed=days_processed,
    )

    return {
        "recalculation_id": str(recalculation_id),
        "experiment_id": experiment.id,
        "metric_uuid": recalculation_request.metric["uuid"],
        "days_processed": days_processed,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }


@temporalio.activity.defn
def backfill_experiment_metric(recalculation_id: str) -> dict[str, Any]:
    """Backfill timeseries data for an experiment recalculation request."""
    return _backfill_experiment_metric_sync(recalculation_id)
