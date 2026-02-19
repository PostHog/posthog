from django.db import models

from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor


class DashboardVisitor(
    ResourceTransferVisitor,
    kind="Dashboard",
    excluded_fields=[
        "data_color_theme_id",
        "data_color_theme",
        "analytics_dashboards",
        "last_refresh",
        "last_accessed_at",
        "share_token",
        "is_shared",
    ],
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from posthog.models import Dashboard

        return Dashboard
