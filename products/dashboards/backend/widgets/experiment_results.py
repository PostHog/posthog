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
from posthog.rbac.user_access_control import UserAccessControl

from products.dashboards.backend.widget_specs.configs import EXPERIMENT_RESULTS_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.models.experiment import Experiment

logger = logging.getLogger(__name__)

# Cap on metrics computed per section (primary, secondary) so one widget can't fan out into many
# ClickHouse queries. Applied independently to each section, so a fully-loaded widget runs at most
# 2x this many queries.
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


def _sort_by_ordered_uuids(metric_dicts: list[dict[str, Any]], ordered_uuids: list[str] | None) -> None:
    if not ordered_uuids:
        return
    order = {uuid: index for index, uuid in enumerate(ordered_uuids)}
    metric_dicts.sort(key=lambda metric: order.get(metric.get("uuid", ""), len(order)))


def _collect_metric_dicts(experiment: Experiment) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Inline metrics plus saved metrics, partitioned into (primary, secondary) in display order when known.

    The saved-metric link set is read once and split here so a widget render issues a single query for it.
    """
    primary: list[dict[str, Any]] = [dict(metric) for metric in (experiment.metrics or [])]
    secondary: list[dict[str, Any]] = [dict(metric) for metric in (experiment.metrics_secondary or [])]

    for link in experiment.experimenttosavedmetric_set.select_related("saved_metric").all():
        saved_query = link.saved_metric.query
        if not saved_query:
            continue
        metric_dict = {**saved_query, "name": saved_query.get("name") or link.saved_metric.name}
        # Links default to primary when untyped; an unrecognized type belongs to neither section.
        metric_type = (link.metadata or {}).get("type", "primary")
        if metric_type == "secondary":
            secondary.append(metric_dict)
        elif metric_type == "primary":
            primary.append(metric_dict)

    _sort_by_ordered_uuids(primary, experiment.primary_metrics_ordered_uuids)
    _sort_by_ordered_uuids(secondary, experiment.secondary_metrics_ordered_uuids)

    return primary, secondary


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
            query=ExperimentQuery(experiment_id=experiment.id, metric=metric),
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

    # Honor object-level experiment access controls, matching the REST endpoint — a user denied
    # access to a specific experiment must not see it (or its results) through the widget.
    access_control = UserAccessControl(user=user, team=team) if user is not None else None

    if experiment_id is None:
        accessible = Experiment.objects.filter(team=team, deleted=False)
        if access_control is not None:
            accessible = access_control.filter_queryset_by_access_level(accessible)
        return {"experiment": None, "metrics": [], "needsConfiguration": True, "hasExperiments": accessible.exists()}

    experiment_queryset = Experiment.objects.filter(id=experiment_id, team=team, deleted=False).select_related(
        "feature_flag"
    )
    if access_control is not None:
        experiment_queryset = access_control.filter_queryset_by_access_level(experiment_queryset)
    experiment = experiment_queryset.first()
    if experiment is None:
        return {"experiment": None, "metrics": [], "experimentNotFound": True}

    payload: dict[str, Any] = {
        "experiment": _serialize_experiment_summary(experiment),
        "metrics": [],
        "secondaryMetrics": [],
    }

    if experiment.start_date is None:
        # Draft experiments have no exposure data yet — nothing to compute.
        return payload

    primary_metric_dicts, secondary_metric_dicts = _collect_metric_dicts(experiment)
    if include_total_count:
        payload["totalMetricsCount"] = len(primary_metric_dicts)
        payload["totalSecondaryMetricsCount"] = len(secondary_metric_dicts)

    with tags_context(product=Product.EXPERIMENTS, feature=Feature.QUERY, team_id=team.pk):
        for index, metric_dict in enumerate(primary_metric_dicts[:MAX_EXPERIMENT_RESULTS_WIDGET_METRICS]):
            payload["metrics"].append(_compute_metric_entry(team, experiment, metric_dict, index))
        for index, metric_dict in enumerate(secondary_metric_dicts[:MAX_EXPERIMENT_RESULTS_WIDGET_METRICS]):
            payload["secondaryMetrics"].append(_compute_metric_entry(team, experiment, metric_dict, index))

    return payload
