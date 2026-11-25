from collections.abc import Mapping

from pydantic import JsonValue

from products.dashboards.backend.dashboard_creation import (
    create_dashboard_with_tiles,
    delete_unlisted_dashboard,
    move_dashboard_tiles,
    read_dashboard_metric_variables,
    read_dashboard_tiles,
)
from products.dashboards.backend.facade.contracts import (
    CreatedDashboard,
    DashboardCreationDenied,
    DashboardTileSnapshot,
    NewDashboard,
    NewInsightTile,
    NewTextTile,
    TileLayout,
)
from products.dashboards.backend.logic import templates as templates_logic

__all__ = [
    "CreatedDashboard",
    "DashboardCreationDenied",
    "DashboardTileSnapshot",
    "NewDashboard",
    "NewInsightTile",
    "NewTextTile",
    "TileLayout",
    "apply_dashboard_template",
    "apply_dashboard_template_json",
    "create_dashboard_with_tiles",
    "delete_unlisted_dashboard",
    "move_dashboard_tiles",
    "read_dashboard_metric_variables",
    "read_dashboard_tiles",
]


def apply_dashboard_template(*, team_id: int, dashboard_id: int, template_key: str, user_id: int | None) -> None:
    """Fill a new dashboard from the saved or code-defined template named `template_key`.

    Raises AttributeError when the team can see no template with that name. The template writes the
    dashboard row, so reload a dashboard model read before the call. With a `user_id`, the insights and
    widgets it adds name that user as their creator, and each widget first checks the user's access to
    its product. Opens no transaction: wrap the call to roll back the tiles of a template that fails part way.
    """
    templates_logic.apply_template_by_key(
        team_id=team_id, dashboard_id=dashboard_id, template_key=template_key, user_id=user_id
    )


def apply_dashboard_template_json(
    *, team_id: int, dashboard_id: int, template: Mapping[str, JsonValue], user_id: int | None
) -> None:
    """Fill a new dashboard from a template body in the `create_from_template_json` request shape.

    Raises KeyError when the body has no `template_name`, `dashboard_description`, `dashboard_filters` or
    `tiles`. What `apply_dashboard_template` says about the dashboard row, the user and the transaction
    applies here too.
    """
    templates_logic.apply_template_json(team_id=team_id, dashboard_id=dashboard_id, template=template, user_id=user_id)
