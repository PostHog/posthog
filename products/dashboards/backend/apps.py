"""Django app configuration for dashboards."""

from django.apps import AppConfig


class DashboardsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.dashboards.backend"
    label = "dashboards"
