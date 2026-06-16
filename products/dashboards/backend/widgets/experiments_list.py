from __future__ import annotations

import logging
from typing import Any

from posthog.models.team import Team
from posthog.models.user import User

from products.dashboards.backend.widget_specs.configs import EXPERIMENTS_LIST_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.experiments.backend.models.experiment import Experiment

logger = logging.getLogger(__name__)

ValidatedExperimentsListWidgetConfig = dict[str, Any]


def derive_experiment_status(experiment: Experiment) -> str:
    """Derive the API-level status (draft/running/paused/stopped) for one experiment row.

    Mirrors ExperimentService.filter_experiments_queryset semantics: paused is a running
    experiment whose linked feature flag is inactive.
    """
    if experiment.status == Experiment.Status.STOPPED or (experiment.status is None and experiment.end_date):
        return "stopped"
    is_running = experiment.status == Experiment.Status.RUNNING or (
        experiment.status is None and experiment.start_date and not experiment.end_date
    )
    if is_running:
        return "running" if experiment.feature_flag.active else "paused"
    return "draft"


def _serialize_experiment_row(experiment: Experiment) -> dict[str, Any]:
    created_by = experiment.created_by
    return {
        "id": experiment.id,
        "name": experiment.name,
        "status": derive_experiment_status(experiment),
        "conclusion": experiment.conclusion,
        "start_date": experiment.start_date.isoformat() if experiment.start_date else None,
        "end_date": experiment.end_date.isoformat() if experiment.end_date else None,
        "created_at": experiment.created_at.isoformat() if experiment.created_at else None,
        "feature_flag_key": experiment.feature_flag.key,
        "created_by": (
            {
                "id": created_by.id,
                "first_name": created_by.first_name,
                "email": created_by.email,
            }
            if created_by
            else None
        ),
    }


def run_experiments_list_widget(
    team: Team,
    config: dict[str, Any],
    user: User | None = None,
    *,
    include_total_count: bool = True,
) -> dict[str, Any]:
    # ExperimentService transitively imports the dashboard API, which loads the widget registry,
    # which imports this module — deferring the import breaks that cycle.
    from products.experiments.backend.experiment_service import ExperimentService  # noqa: PLC0415

    typed_config = validate_widget_config(EXPERIMENTS_LIST_WIDGET_TYPE, config)
    limit = typed_config["limit"]

    order_by = typed_config.get("orderBy", "created_at")
    order_prefix = "-" if typed_config.get("orderDirection", "DESC") == "DESC" else ""
    query_params: dict[str, Any] = {"status": typed_config["status"], "order": f"{order_prefix}{order_by}"}
    created_by = typed_config.get("createdBy")
    if created_by is not None:
        query_params["created_by_id"] = created_by

    base_queryset = Experiment.objects.filter(team=team).select_related("created_by", "feature_flag")
    service = ExperimentService(team=team, user=user)
    queryset = service.filter_experiments_queryset(base_queryset, action="list", query_params=query_params)

    total_count = queryset.count()
    experiments = list(queryset[:limit])

    return {
        "results": [_serialize_experiment_row(experiment) for experiment in experiments],
        "hasMore": total_count > limit,
        "limit": limit,
        "offset": 0,
        "totalCount": total_count,
        "totalCountCapped": False,
    }
