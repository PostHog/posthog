from django.db import models

from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor


class DashboardTileVisitor(
    ResourceTransferVisitor,
    kind="DashboardTile",
    excluded_fields=[
        "filters_hash",
        "last_refresh",
        "refreshing",
        "refresh_attempt",
    ],
    friendly_name="Dashboard tile",
    user_facing=False,
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from posthog.models import DashboardTile

        return DashboardTile
