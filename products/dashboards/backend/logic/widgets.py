"""Dashboard widget tiles."""

from collections.abc import Mapping

from pydantic import JsonValue

from products.dashboards.backend.widget_specs.configs import CONVERSATIONS_RECENT_TICKETS_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import EXPECTED_WIDGET_TYPES


def public_widget_config(widget_type: str, config: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    # Rows of a retired widget type can still exist, and nothing says which of their config keys are public.
    if widget_type not in EXPECTED_WIDGET_TYPES:
        return {}
    public_config = dict(config)
    if widget_type == CONVERSATIONS_RECENT_TICKETS_WIDGET_TYPE:
        public_config.pop("search", None)
    return public_config
