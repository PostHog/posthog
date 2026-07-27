from __future__ import annotations

from typing import Any

from django.db import models

from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor

from products.dashboards.backend.models.dashboard_widget import DashboardWidget
from products.dashboards.backend.widget_catalog import WIDGET_CATALOG


class DashboardWidgetVisitor(
    ResourceTransferVisitor,
    kind="DashboardWidget",
    excluded_fields=["last_modified_at"],
    friendly_name="Dashboard widget",
    user_facing=False,
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        return DashboardWidget

    @classmethod
    def get_display_name(cls, resource: Any) -> str:
        if getattr(resource, "name", None):
            return str(resource.name)

        widget_type = getattr(resource, "widget_type", None)
        if widget_type:
            catalog_entry = WIDGET_CATALOG.get(str(widget_type))
            if catalog_entry is not None:
                return catalog_entry["label"]
            return str(widget_type)

        return super().get_display_name(resource)
