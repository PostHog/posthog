"""
Widget config models, for the OpenAPI serializers in presentation.

Each widget type validates its tile config with a Pydantic model. The API schema builds the typed
widget config and catalog components from these models and from ``WidgetFilterEntry``, which the
list widgets share.
"""

from collections.abc import Mapping

from pydantic import BaseModel

from products.dashboards.backend.widget_specs.common import WidgetFilterEntry
from products.dashboards.backend.widget_specs.registry import WIDGET_SPECS

# Keyed by widget type, in registry order. The schema lists the components in this order.
WIDGET_CONFIG_MODELS: Mapping[str, type[BaseModel]] = {
    widget_type: spec.config_model for widget_type, spec in WIDGET_SPECS.items()
}

__all__ = ["WIDGET_CONFIG_MODELS", "WidgetFilterEntry"]
