from datetime import datetime
from typing import Union

import structlog

from posthog.schema import ExperimentFunnelMetric, ExperimentMeanMetric, ExperimentRatioMetric

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event

from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult as ExperimentMetricResultModel,
)

logger = structlog.get_logger(__name__)

# Default hour (UTC) for experiment recalculation when team has no specific time set
DEFAULT_EXPERIMENT_RECALCULATION_HOUR = 2  # 02:00 UTC


def get_metric(metric_data: dict) -> Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric]:
    metric_type = metric_data.get("metric_type")
    if metric_type == "mean":
        return ExperimentMeanMetric(**metric_data)
    elif metric_type == "funnel":
        return ExperimentFunnelMetric(**metric_data)
    elif metric_type == "ratio":
        return ExperimentRatioMetric(**metric_data)
    else:
        raise ValueError(f"Unknown metric type: {metric_type}")


def _get_significant_variant_keys(result_dict: dict) -> set[str]:
    variant_results = result_dict.get("variant_results") or []
    return {v["key"] for v in variant_results if v.get("significant")}


def _get_variant_result(result_dict: dict, variant_key: str) -> dict | None:
    for v in result_dict.get("variant_results") or []:
        if v.get("key") == variant_key:
            return v
    return None


def _get_relative_change(result_dict: dict, variant_key: str) -> str | None:
    baseline = result_dict.get("baseline")
    variant = _get_variant_result(result_dict, variant_key)
    if not baseline or not variant:
        return None
    baseline_count = baseline.get("number_of_samples") or 0
    variant_count = variant.get("number_of_samples") or 0
    if baseline_count == 0 or variant_count == 0:
        return None
    baseline_mean = (baseline.get("sum") or 0) / baseline_count
    variant_mean = (variant.get("sum") or 0) / variant_count
    if baseline_mean == 0:
        return None
    pct = (variant_mean - baseline_mean) / baseline_mean * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{round(pct)}%"


def _get_source_name(source: dict) -> str | None:
    kind = source.get("kind")
    if kind == "EventsNode":
        return source.get("custom_name") or source.get("name") or source.get("event")
    elif kind == "ActionsNode":
        name = source.get("custom_name") or source.get("name")
        return name or f"Action {source.get('id')}"
    elif kind == "ExperimentDataWarehouseNode":
        return source.get("table_name")
    return None


def _get_metric_name(metric_dict: dict) -> str:
    if metric_dict.get("name"):
        return metric_dict["name"]
    metric_type = metric_dict.get("metric_type")
    if metric_type == "mean":
        source = metric_dict.get("source", {})
        return _get_source_name(source) or "Untitled metric"
    elif metric_type == "funnel":
        series = metric_dict.get("series", [])
        return (_get_source_name(series[0]) or "Untitled funnel") if series else "Untitled funnel"
    elif metric_type == "ratio":
        num = _get_source_name(metric_dict.get("numerator", {})) or "Numerator"
        den = _get_source_name(metric_dict.get("denominator", {})) or "Denominator"
        return f"{num} / {den}"
    elif metric_type == "retention":
        start = _get_source_name(metric_dict.get("start_event", {})) or "Start event"
        completion = _get_source_name(metric_dict.get("completion_event", {})) or "Completion event"
        return f"{start} / {completion}"
    return "Untitled metric"


def _find_metric_dict(experiment: Experiment, metric_uuid: str) -> dict | None:
    all_metrics = (experiment.metrics or []) + (experiment.metrics_secondary or [])
    for m in all_metrics:
        if m.get("uuid") == metric_uuid:
            return m
    for link in experiment.experimenttosavedmetric_set.select_related("saved_metric").all():
        query = link.saved_metric.query
        if isinstance(query, dict) and query.get("uuid") == metric_uuid:
            return query
    return None


def check_significance_transition(
    experiment: Experiment,
    metric_uuid: str,
    fingerprint: str,
    result_dict: dict,
    query_to_utc: datetime,
) -> None:
    try:
        new_significant_keys = _get_significant_variant_keys(result_dict)
        if not new_significant_keys:
            return

        previous = (
            ExperimentMetricResultModel.objects.filter(
                experiment=experiment,
                metric_uuid=metric_uuid,
                fingerprint=fingerprint,
                status=ExperimentMetricResultModel.Status.COMPLETED,
                query_to__lt=query_to_utc,
            )
            .order_by("-query_to")
            .first()
        )

        prev_significant_keys = (
            _get_significant_variant_keys(previous.result) if previous and previous.result else set()
        )
        newly_significant = new_significant_keys - prev_significant_keys

        if not newly_significant:
            return

        experiment_url = f"/experiments/{experiment.id}"

        metric_dict = _find_metric_dict(experiment, metric_uuid)
        metric_name = _get_metric_name(metric_dict) if metric_dict else "Untitled metric"
        goal_direction = metric_dict.get("goal_direction", "increase") if metric_dict else "increase"

        for variant_key in newly_significant:
            variant_result = _get_variant_result(result_dict, variant_key)
            chance_to_win_raw = variant_result.get("chance_to_win", 0) if variant_result else 0
            chance_to_win = f"{round(chance_to_win_raw * 100)}%"
            raw_change = _get_relative_change(result_dict, variant_key)
            relative_change = f"({raw_change})" if raw_change else ""

            logger.info(
                "Producing internal event for experiment significance transition",
                experiment_id=experiment.id,
                metric_uuid=metric_uuid,
                variant_key=variant_key,
            )

            produce_internal_event(
                team_id=experiment.team_id,
                event=InternalEventEvent(
                    event="$experiment_metric_significant",
                    distinct_id=f"team_{experiment.team_id}",
                    properties={
                        "experiment_id": experiment.id,
                        "experiment_name": experiment.name,
                        "metric_uuid": metric_uuid,
                        "variant_key": variant_key,
                        "metric_name": metric_name,
                        "goal_direction": goal_direction,
                        "chance_to_win": chance_to_win,
                        "relative_change": relative_change or "",
                        "experiment_url": experiment_url,
                    },
                ),
            )
    except Exception:
        logger.warning(
            "Significance transition check failed, skipping notification",
            experiment_id=experiment.id,
            metric_uuid=metric_uuid,
        )
