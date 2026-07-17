from datetime import datetime, timedelta
from typing import Any, Union
from zoneinfo import ZoneInfo

from django.db import close_old_connections
from django.db.models import Q

import structlog
import temporalio.activity

from posthog.schema import ExperimentFunnelMetric, ExperimentMeanMetric, ExperimentQuery, ExperimentRatioMetric

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import tag_queries
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.experiments.models import (
    TIMESERIES_METRIC_MAX_ATTEMPTS,
    ExperimentRegularMetricInput,
    ExperimentRegularMetricResult,
    ExperimentSavedMetricInput,
    ExperimentSavedMetricResult,
)
from posthog.temporal.experiments.utils import DEFAULT_EXPERIMENT_RECALCULATION_HOUR, check_significance_transition

from products.experiments.backend.facade.timeseries import backfill_experiment_timeseries
from products.experiments.backend.hogql_queries.base_query_utils import experiment_window_end
from products.experiments.backend.hogql_queries.error_handling import capture_experiment_metric_error_event
from products.experiments.backend.hogql_queries.experiment_metric_fingerprint import compute_metric_fingerprint
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.hogql_queries.utils import get_experiment_stats_method
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult as ExperimentMetricResultModel,
)
from products.experiments.stats.shared.statistics import StatisticError

logger = structlog.get_logger(__name__)

EXPERIMENT_RECALCULATION_MAX_AGE_DAYS = 60


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
        start_date__gte=datetime.now(ZoneInfo("UTC")) - timedelta(days=EXPERIMENT_RECALCULATION_MAX_AGE_DAYS),
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
    attempt: int = 1,
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
    now_utc = datetime.now(ZoneInfo("UTC"))
    query_to_utc = experiment_window_end(experiment, now_utc)

    try:
        experiment_query = ExperimentQuery(
            experiment_id=experiment_id,
            metric=metric_obj,
        )

        query_runner = ExperimentQueryRunner(
            query=experiment_query,
            team=experiment.team,
            as_of=query_to_utc,
            workload=Workload.OFFLINE,
            # Scheduled recalc has no request user. Attribute the query to the experiment's creator so
            # warehouse HogQL access control is enforced.
            user=experiment.created_by,
            # Internal caller: keep exceptions raw so the except branches below see original types
            # (StatisticError must not arrive pre-converted to ValidationError). Also silences the
            # runner-level error event — this activity emits its own, on the final attempt.
            user_facing=False,
        )
        # .run() writes to the response cache. The "warming/*" trigger tells
        # run() this is a scheduled job, not a user query, so it skips logging
        # the events as "used by this team."
        tag_queries(trigger="warming/experiment_timeseries")
        result = query_runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        result_dict = result.model_dump(mode="json")

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

        # Permanent failure, returned (not raised) — terminal on the first attempt.
        capture_experiment_metric_error_event(
            team=experiment.team,
            error=e,
            context="scheduled",
            mechanism="orchestrated",
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            metric_kind=metric_type,
            user=experiment.created_by,
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

        # Temporal retries this activity; emit only when retries are exhausted so a transient
        # failure that recovers on a later attempt is never counted.
        if attempt >= TIMESERIES_METRIC_MAX_ATTEMPTS:
            capture_experiment_metric_error_event(
                team=experiment.team,
                error=e,
                context="scheduled",
                mechanism="orchestrated",
                experiment_id=experiment_id,
                metric_uuid=metric_uuid,
                metric_kind=metric_type,
                user=experiment.created_by,
            )

        raise


@temporalio.activity.defn
async def calculate_experiment_regular_metric(
    experiment_id: int,
    metric_uuid: str,
    fingerprint: str,
) -> ExperimentRegularMetricResult:
    """Calculate timeseries results for a single experiment-metric combination."""
    return await _calculate_experiment_regular_metric_sync(
        experiment_id, metric_uuid, fingerprint, attempt=temporalio.activity.info().attempt
    )


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
        start_date__gte=datetime.now(ZoneInfo("UTC")) - timedelta(days=EXPERIMENT_RECALCULATION_MAX_AGE_DAYS),
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
    attempt: int = 1,
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
    saved_metric_metadata: dict = {}
    for exp_to_sm in experiment.experimenttosavedmetric_set.select_related("saved_metric").all():
        if exp_to_sm.saved_metric.query.get("uuid") == metric_uuid:
            saved_metric = exp_to_sm.saved_metric
            saved_metric_metadata = exp_to_sm.metadata or {}
            break

    if not saved_metric:
        return ExperimentSavedMetricResult(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            fingerprint=fingerprint,
            success=False,
            error_message=f"Saved metric {metric_uuid} not found for experiment {experiment_id}",
        )

    # The frontend receives saved metrics with two extra fields injected before
    # they get posted back to /query: a breakdownFilter wrapper (from the link
    # metadata, via sharedMetricsToExperimentMetrics in experimentLogic.tsx) and
    # a fingerprint (added by the experiment API serializer). The activity must
    # apply both or the response cache key diverges from /query's.
    query = {
        **saved_metric.query,
        "breakdownFilter": {
            **(saved_metric.query.get("breakdownFilter") or {}),
            "breakdowns": saved_metric_metadata.get("breakdowns") or [],
        },
        "fingerprint": fingerprint,
    }
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
    now_utc = datetime.now(ZoneInfo("UTC"))
    query_to_utc = experiment_window_end(experiment, now_utc)

    try:
        experiment_query = ExperimentQuery(
            experiment_id=experiment_id,
            metric=metric_obj,
        )

        query_runner = ExperimentQueryRunner(
            query=experiment_query,
            team=experiment.team,
            as_of=query_to_utc,
            workload=Workload.OFFLINE,
            # Scheduled recalc has no request user. Attribute the query to the experiment's creator so
            # warehouse HogQL access control is enforced.
            user=experiment.created_by,
            # Internal caller: keep exceptions raw so the except branches below see original types
            # (StatisticError must not arrive pre-converted to ValidationError). Also silences the
            # runner-level error event — this activity emits its own, on the final attempt.
            user_facing=False,
        )
        # .run() writes to the response cache. The "warming/*" trigger tells
        # run() this is a scheduled job, not a user query, so it skips logging
        # the events as "used by this team."
        tag_queries(trigger="warming/experiment_timeseries")
        result = query_runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        result_dict = result.model_dump(mode="json")

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

        # Permanent failure, returned (not raised) — terminal on the first attempt.
        capture_experiment_metric_error_event(
            team=experiment.team,
            error=e,
            context="scheduled",
            mechanism="orchestrated",
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            metric_kind=metric_type,
            user=experiment.created_by,
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

        # Temporal retries this activity; emit only when retries are exhausted so a transient
        # failure that recovers on a later attempt is never counted.
        if attempt >= TIMESERIES_METRIC_MAX_ATTEMPTS:
            capture_experiment_metric_error_event(
                team=experiment.team,
                error=e,
                context="scheduled",
                mechanism="orchestrated",
                experiment_id=experiment_id,
                metric_uuid=metric_uuid,
                metric_kind=metric_type,
                user=experiment.created_by,
            )

        raise


@temporalio.activity.defn
async def calculate_experiment_saved_metric(
    experiment_id: int,
    metric_uuid: str,
    fingerprint: str,
) -> ExperimentSavedMetricResult:
    """Calculate timeseries results for a single experiment-saved metric combination."""
    return await _calculate_experiment_saved_metric_sync(
        experiment_id, metric_uuid, fingerprint, attempt=temporalio.activity.info().attempt
    )


@temporalio.activity.defn
def backfill_experiment_metric(recalculation_id: str) -> dict[str, Any]:
    """Backfill timeseries data for an experiment recalculation request."""
    close_old_connections()
    with HeartbeaterSync(logger=logger):
        return backfill_experiment_timeseries(recalculation_id)
