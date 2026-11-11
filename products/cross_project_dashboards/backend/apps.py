"""Django app configuration for cross_project_dashboards."""

from django.apps import AppConfig


class CrossProjectDashboardsConfig(AppConfig):
    name = "products.cross_project_dashboards.backend"
    label = "cross_project_dashboards"

    def ready(self) -> None:
        # Models are not loaded when this module is imported, so the activity receiver cannot
        # be wired at module level. Dashboards are also mutated outside web requests, so this
        # must connect in every process.
        from products.cross_project_dashboards.backend import activity_logging  # noqa: F401, PLC0415
