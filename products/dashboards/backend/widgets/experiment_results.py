from __future__ import annotations

from dataclasses import asdict
from typing import Any

from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.widget_specs.configs import EXPERIMENT_RESULTS_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.experiments.backend.facade.dashboard_widgets import experiment_results_widget, has_accessible_experiments

# Cap on metrics computed per section (primary, secondary) so one widget can't fan out into many
# ClickHouse queries. Applied independently to each section, so a fully-loaded widget runs at most
# 2x this many queries.
MAX_EXPERIMENT_RESULTS_WIDGET_METRICS = 3


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
        return {
            "experiment": None,
            "metrics": [],
            "needsConfiguration": True,
            "hasExperiments": has_accessible_experiments(team, access_control),
        }

    experiment = experiment_results_widget(
        team, access_control, experiment_id=experiment_id, max_metrics_per_section=MAX_EXPERIMENT_RESULTS_WIDGET_METRICS
    )
    if experiment is None:
        return {"experiment": None, "metrics": [], "experimentNotFound": True}

    payload: dict[str, Any] = {
        "experiment": {
            "id": experiment.id,
            "name": experiment.name,
            "status": experiment.status,
            "start_date": experiment.start_date.isoformat() if experiment.start_date else None,
            "end_date": experiment.end_date.isoformat() if experiment.end_date else None,
            "feature_flag_key": experiment.feature_flag_key,
        },
        "metrics": [],
        "secondaryMetrics": [],
    }

    if experiment.metrics is None:
        return payload

    if include_total_count:
        payload["totalMetricsCount"] = experiment.metrics.primary_total
        payload["totalSecondaryMetricsCount"] = experiment.metrics.secondary_total
    payload["metrics"] = [asdict(metric) for metric in experiment.metrics.primary]
    payload["secondaryMetrics"] = [asdict(metric) for metric in experiment.metrics.secondary]

    return payload
