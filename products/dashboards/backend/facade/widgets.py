"""
Dashboard widget types and widget runs, for the dashboards API.

The widget functions that check the requester's product access take a `UserAccessControl`, so they
live in `api.py` with the other functions that take one: `widget_product_access_error`,
`validate_new_widget`, `create_widget_tiles` and `update_widget`.
"""

from collections.abc import Mapping, Sequence
from functools import cache

from pydantic import JsonValue

from posthog.models.team import Team
from posthog.models.user import User

from products.dashboards.backend.facade.contracts import (
    WidgetCatalogEntry,
    WidgetRun,
    WidgetRunRefusal,
    WidgetRunResult,
)
from products.dashboards.backend.logic import widgets as widgets_logic
from products.dashboards.backend.widget_availability import get_widget_feature_enabled
from products.dashboards.backend.widget_catalog import get_widget_catalog_entries
from products.dashboards.backend.widget_specs import registry as widget_registry

EXPECTED_WIDGET_TYPES: frozenset[str] = widget_registry.EXPECTED_WIDGET_TYPES


@cache
def _catalog_entries() -> dict[str, WidgetCatalogEntry]:
    return {
        entry["widget_type"]: WidgetCatalogEntry(
            widget_type=entry["widget_type"],
            group_id=entry["group_id"],
            group_label=entry["group_label"],
            label=entry["label"],
            description=entry["description"],
            config_schema=entry["config_schema"],
            required_product_access=entry["required_product_access"],
            product_access_denied_message=entry.get("product_access_denied_message"),
            availability_requirements=tuple(entry["availability_requirements"]),
            live=entry["live"],
        )
        for entry in get_widget_catalog_entries()
    }


def widget_catalog(widget_types: Sequence[str] | None = None) -> tuple[WidgetCatalogEntry, ...]:
    """The catalog entries of these widget types, in registry order. No types means every registered type."""
    entries = _catalog_entries()
    return tuple(entries[entry["widget_type"]] for entry in get_widget_catalog_entries(widget_types))


def widget_feature_enabled(*, widget_type: str, team: Team) -> bool | None:
    """Whether the features a widget type needs are on for the team. None when the type declares none or one is unknown."""
    return get_widget_feature_enabled(widget_type, team)


def public_widget_config(*, widget_type: str, config: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """The part of a widget config that a shared dashboard may show."""
    return widgets_logic.public_widget_config(widget_type, config)


def plan_widget_runs(*, dashboard_id: int, tile_ids: Sequence[int]) -> tuple[WidgetRun | WidgetRunRefusal, ...]:
    """One plan per requested tile id, in request order. The caller checks access and throttles before it runs a plan."""
    return widgets_logic.plan_widget_runs(dashboard_id=dashboard_id, tile_ids=tile_ids)


def run_widget(*, team: Team, user: User, dashboard_id: int, run: WidgetRun) -> WidgetRunResult:
    """Run one widget query, inside the dashboard widget delivery SLO. A failed query gives a result with an error."""
    return widgets_logic.run_widget(team=team, user=user, dashboard_id=dashboard_id, run=run)


__all__ = [
    "EXPECTED_WIDGET_TYPES",
    "plan_widget_runs",
    "public_widget_config",
    "run_widget",
    "widget_catalog",
    "widget_feature_enabled",
]
