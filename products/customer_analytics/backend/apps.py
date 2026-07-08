from django.apps import AppConfig


class CustomerAnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.customer_analytics.backend"
    label = "customer_analytics"

    def ready(self) -> None:
        from . import signals  # noqa: F401
