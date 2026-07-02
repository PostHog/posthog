"""Public facade for the demo product.

Core (`posthog/`, `ee/`) generates demo/simulation data only through the surface exposed
here — signup, the demo celery tasks, the `generate_demo_data`/`setup_dev`/eval tooling,
and the `demo_route` view. The matrix scenario classes cross the boundary as objects core
instantiates; the data-generation helpers are thin functions over the product's logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from products.demo.backend.logic.dashboard_template_seeds import (
    seed_dev_dashboard_templates as _seed_dev_dashboard_templates,
)
from products.demo.backend.logic.legacy import (
    ORGANIZATION_NAME,
    TEAM_NAME,
    create_demo_data as _create_demo_data,
    demo_route,
)
from products.demo.backend.logic.matrix import Matrix, MatrixManager
from products.demo.backend.logic.matrix.persons_db_sync import (
    get_group_type_mapping_count as _get_group_type_mapping_count,
)
from products.demo.backend.logic.matrix.taxonomy_inference import infer_taxonomy_for_team as _infer_taxonomy_for_team
from products.demo.backend.logic.products.hedgebox import HedgeboxMatrix
from products.demo.backend.logic.products.hedgebox.taxonomy import (
    SITE_URL,
    URL_FILES,
    URL_HOME,
    URL_LOGIN,
    URL_MARIUS_TECH_TIPS,
    URL_PRICING,
    URL_SIGNUP,
)
from products.demo.backend.logic.products.spikegpt import SpikeGPTMatrix

if TYPE_CHECKING:
    from posthog.models.team import Team


def create_demo_data(team: Team, dashboards: bool = True) -> None:
    _create_demo_data(team, dashboards=dashboards)


def seed_dev_dashboard_templates() -> list[str]:
    return _seed_dev_dashboard_templates()


def infer_taxonomy_for_team(team_id: int) -> tuple[int, int, int]:
    return _infer_taxonomy_for_team(team_id)


def get_group_type_mapping_count(project_id: int) -> int:
    return _get_group_type_mapping_count(project_id)


__all__ = [
    "ORGANIZATION_NAME",
    "SITE_URL",
    "TEAM_NAME",
    "URL_FILES",
    "URL_HOME",
    "URL_LOGIN",
    "URL_MARIUS_TECH_TIPS",
    "URL_PRICING",
    "URL_SIGNUP",
    "HedgeboxMatrix",
    "Matrix",
    "MatrixManager",
    "SpikeGPTMatrix",
    "create_demo_data",
    "demo_route",
    "get_group_type_mapping_count",
    "infer_taxonomy_for_team",
    "seed_dev_dashboard_templates",
]
