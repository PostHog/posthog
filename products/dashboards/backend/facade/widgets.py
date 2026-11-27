"""
Dashboard widget types, for the dashboards API.
"""

from collections.abc import Mapping, Sequence
from functools import cache

from pydantic import JsonValue

from posthog.models.team import Team

from products.dashboards.backend.facade.contracts import WidgetCatalogEntry
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


__all__ = [
    "EXPECTED_WIDGET_TYPES",
    "public_widget_config",
    "widget_catalog",
    "widget_feature_enabled",
]
