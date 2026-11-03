from __future__ import annotations

from typing import Any

from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.constants import MAX_WIDGET_RESULT_LIMIT
from products.dashboards.backend.widget_specs.configs import EXPERIMENTS_LIST_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.dashboards.backend.widgets.list_widget import ListWidgetPage, run_list_widget
from products.experiments.backend.facade.contracts import ExperimentListWidgetRow
from products.experiments.backend.facade.dashboard_widgets import experiments_list_widget_page

ValidatedExperimentsListWidgetConfig = dict[str, Any]


def _serialize_experiment_row(experiment: ExperimentListWidgetRow) -> dict[str, Any]:
    created_by = experiment.created_by
    return {
        "id": experiment.id,
        "name": experiment.name,
        "status": experiment.status,
        "conclusion": experiment.conclusion,
        "start_date": experiment.start_date.isoformat() if experiment.start_date else None,
        "end_date": experiment.end_date.isoformat() if experiment.end_date else None,
        "created_at": experiment.created_at.isoformat(),
        "feature_flag_key": experiment.feature_flag_key,
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
    typed_config = validate_widget_config(EXPERIMENTS_LIST_WIDGET_TYPE, config)
    limit = typed_config["limit"]
    # One instance serves both page fetches, so the access-control rows load once.
    access = UserAccessControl(user=user, team=team) if user is not None else None

    def fetch_page(page_limit: int) -> ListWidgetPage:
        page = experiments_list_widget_page(
            team,
            access,
            status=typed_config["status"],
            order_by=typed_config.get("orderBy", "created_at"),
            descending=typed_config.get("orderDirection", "DESC") == "DESC",
            created_by_id=typed_config.get("createdBy"),
            limit=page_limit,
        )
        return ListWidgetPage(results=list(page.rows), has_more=page.has_more, next_offset=page_limit)

    return run_list_widget(
        limit=limit,
        count_cap=MAX_WIDGET_RESULT_LIMIT,
        include_total_count=include_total_count,
        fetch_page=fetch_page,
        transform_row=_serialize_experiment_row,
        log_key="experiments_list_widget_total_count_failed",
    )
