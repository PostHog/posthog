from django.db import models

from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor


class ButtonTileVisitor(
    ResourceTransferVisitor, kind="ButtonTile", excluded_fields=["last_modified_at"], user_facing=False
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from products.dashboards.backend.models.dashboard_tile import ButtonTile

        return ButtonTile
