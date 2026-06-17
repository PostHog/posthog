from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from posthog.schema import (
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentQuery,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
)

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.team import Team
from posthog.models.user import User

from products.dashboards.backend.widget_specs.configs import EXPERIMENT_RESULTS_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.models.experiment import Experiment

logger = logging.getLogger(__name__)

# Cap on metrics computed per tile so one widget can't fan out into many ClickHouse queries.
MAX_EXPERIMENT_RESULTS_WIDGET_METRICS = 3

_METRIC_BUILDERS: dict[str, type[BaseModel]] = {
    "mean": ExperimentMeanMetric,
    "funnel": ExperimentFunnelMetric,
    "ratio": ExperimentRatioMetric,
    "retention": ExperimentRetentionMetric,
}


def _serialize_experiment_summary(experiment: Experiment) -> dict[str, Any]:
    return {
        "id": experiment.id,
        "name": experiment.name,
        "status": experiment.status_label,
        "start_date": experiment.start_date.isoformat() if experiment.start_date else None,
        "end_date": experiment.end_date.isoformat() if experiment.end_date else None,
        "feature_flag_key": experiment.feature_flag.key,
    }


def _collect_primary_metric_dicts(experiment: Experiment) -> list[dict[str, Any]]:
    """Inline primary metrics plus saved metrics linked as primary, in display order when known."""
    metric_dicts: list[dict[str, Any]] = [dict(metric) for metric in (experiment.metrics or [])]

    for link in experiment.experimenttosavedmetric_set.select_related("saved_metric").all():
        metadata = link.metadata or {}
        if metadata.get("type", "primary") != "primary":
            continue
        saved_query = link.saved_metric.query
        if not saved_query:
            continue
        metric_dicts.append({**saved_query, "name": saved_query.get("name") or link.saved_metric.name})

    ordered_uuids = experiment.primary_metrics_ordered_uuids
    if ordered_uuids:
        order = {uuid: index for index, uuid in enumerate(ordered_uuids)}
        metric_dicts.sort(key=lambda metric: order.get(metric.get("uuid"), len(order)))

    return metric_dicts


def _compute_metric_entry(
    team: Team, experiment: Experiment, metric_dict: dict[str, Any], index: int
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "uuid": metric_dict.get("uuid"),
        "name": metric_dict.get("name") or f"Metric {index + 1}",
        "metric": None,
        "result": None,
        "error": None,
    }

    metric_builder = _METRIC_BUILDERS.get(metric_dict.get("metric_type", ""))
    if metric_dict.get("kind") != "ExperimentMetric" or metric_builder is None:
        entry["error"] = "Legacy metrics are not supported in this widget."
        return entry

    try:
        metric = metric_builder.model_validate(metric_dict)
        runner = ExperimentQueryRunner(
            query=ExperimentQuery(experiment_id=experiment.id, metric=metric),  # type: ignore[arg-type]
            team=team,
        )
        response = runner.run(execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE)
        result_dict = response.model_dump(mode="json")
        entry["metric"] = metric.model_dump(mode="json")
        # Strip per-variant session payloads and debug SQL — the widget only renders the scorecard.
        for key in ("clickhouse_sql", "hogql", "insight", "query_status"):
            result_dict.pop(key, None)
        entry["result"] = result_dict
    except Exception:
        logger.exception(
            "experiment_results_widget_metric_failed",
            extra={"experiment_id": experiment.id, "metric_uuid": metric_dict.get("uuid")},
        )
        entry["error"] = "Could not compute results for this metric."

    return entry


def run_experiment_results_widget(
    team: Team,
    config: dict[str, Any],
    user: User | None = None,
    *,
    include_total_count: bool = True,
) -> dict[str, Any]:
    typed_config = validate_widget_config(EXPERIMENT_RESULTS_WIDGET_TYPE, config)
    experiment_id = typed_config.get("experimentId")

    if experiment_id is None:
        has_experiments = Experiment.objects.filter(team=team, deleted=False).exists()
        return {"experiment": None, "metrics": [], "needsConfiguration": True, "hasExperiments": has_experiments}

    experiment = (
        Experiment.objects.filter(id=experiment_id, team=team, deleted=False).select_related("feature_flag").first()
    )
    if experiment is None:
        return {"experiment": None, "metrics": [], "experimentNotFound": True}

    payload: dict[str, Any] = {
        "experiment": _serialize_experiment_summary(experiment),
        "metrics": [],
    }

    if experiment.start_date is None:
        # Draft experiments have no exposure data yet — nothing to compute.
        return payload

    metric_dicts = _collect_primary_metric_dicts(experiment)
    if include_total_count:
        payload["totalMetricsCount"] = len(metric_dicts)

    with tags_context(product=Product.EXPERIMENTS, feature=Feature.QUERY, team_id=team.pk):
        for index, metric_dict in enumerate(metric_dicts[:MAX_EXPERIMENT_RESULTS_WIDGET_METRICS]):
            payload["metrics"].append(_compute_metric_entry(team, experiment, metric_dict, index))

    return payload
