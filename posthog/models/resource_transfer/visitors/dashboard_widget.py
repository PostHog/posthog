from __future__ import annotations

from typing import Any

from django.db import models

from posthog.models.resource_transfer.registered_models import registered_model
from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor

from products.dashboards.backend.facade.api import widget_type_label


class DashboardWidgetVisitor(
    ResourceTransferVisitor,
    kind="DashboardWidget",
    excluded_fields=["last_modified_at"],
    friendly_name="Dashboard widget",
    user_facing=False,
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        # The dashboards product registers its model from its AppConfig.ready().
        return registered_model("DashboardWidget")

    @classmethod
    def get_display_name(cls, resource: Any) -> str:
        if getattr(resource, "name", None):
            return str(resource.name)

        widget_type = getattr(resource, "widget_type", None)
        if widget_type:
            label = widget_type_label(str(widget_type))
            return label if label is not None else str(widget_type)

        return super().get_display_name(resource)
