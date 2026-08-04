from typing import Any

from django.db import models

from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor


class ButtonTileVisitor(
    ResourceTransferVisitor,
    kind="ButtonTile",
    excluded_fields=["last_modified_at"],
    friendly_name="Button tile",
    user_facing=False,
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from products.dashboards.backend.models.dashboard_tile import ButtonTile

        return ButtonTile

    @classmethod
    def get_display_name(cls, resource: Any) -> str:
        if getattr(resource, "text", None):
            return str(resource.text)

        return super().get_display_name(resource)
