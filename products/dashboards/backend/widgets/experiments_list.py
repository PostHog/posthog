from __future__ import annotations

from typing import Any

from posthog.models.team import Team
from posthog.models.user import User
from posthog.rbac.user_access_control import UserAccessControl

from products.dashboards.backend.constants import MAX_WIDGET_RESULT_LIMIT
from products.dashboards.backend.widget_specs.configs import EXPERIMENTS_LIST_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.dashboards.backend.widgets.list_widget import ListWidgetPage, run_list_widget
from products.experiments.backend.models.experiment import Experiment

ValidatedExperimentsListWidgetConfig = dict[str, Any]


def _serialize_experiment_row(experiment: Experiment) -> dict[str, Any]:
    created_by = experiment.created_by
    return {
        "id": experiment.id,
        "name": experiment.name,
        "status": experiment.status_label,
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

    if user is not None:
        # Honor object-level experiment access controls, matching the REST list endpoint.
        queryset = UserAccessControl(user=user, team=team).filter_queryset_by_access_level(queryset)

    def fetch_page(page_limit: int) -> ListWidgetPage:
        rows = list(queryset[: page_limit + 1])
        return ListWidgetPage(results=rows[:page_limit], has_more=len(rows) > page_limit, next_offset=page_limit)

    return run_list_widget(
        limit=limit,
        count_cap=MAX_WIDGET_RESULT_LIMIT,
        include_total_count=include_total_count,
        fetch_page=fetch_page,
        transform_row=_serialize_experiment_row,
        log_key="experiments_list_widget_total_count_failed",
    )
