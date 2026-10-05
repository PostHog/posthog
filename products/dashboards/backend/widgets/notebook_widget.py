from posthog.models import Team, User

from products.dashboards.backend.widget_specs.configs import NOTEBOOK_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import validate_widget_config


def run_notebook_widget(
    team: Team, config: dict[str, object], user: User | None = None, *, include_total_count: bool = True
) -> dict[str, object]:
    # Results use the notebook endpoints so their object, query, and source permissions also apply here.
    return validate_widget_config(NOTEBOOK_WIDGET_TYPE, config)
