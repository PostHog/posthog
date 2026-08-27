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
        # Reverse M2M from an AI report's context; not an owned relation to copy, and visiting its
        # auto-created through model has no visitor. Mirrors subscriptions_dashboard_export on Insight.
        "contextual_ai_subscriptions",
    ],
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from products.dashboards.backend.models.dashboard import Dashboard

        return Dashboard
