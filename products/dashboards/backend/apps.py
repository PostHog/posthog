"""Django app configuration for dashboards."""

from django.apps import AppConfig


class DashboardsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.dashboards.backend"
    label = "dashboards"

    def ready(self) -> None:
        # Connect the dashboard/dashboard-widget activity-log receivers at app-population. They used
        # to wire in as an import side effect of the viewset module; the lazy API router no longer
        # pulls that, so a process that never builds the router (celery, temporal, migrate) would
        # drop audit logs on dashboard writes. They live in a light activity_logging module because
        # the dashboard viewset pulls scipy via the error-tracking widget query runners.
        from products.dashboards.backend import activity_logging  # noqa: F401, PLC0415
