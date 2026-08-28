from django.apps import AppConfig


class BillingAlertsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.billing_alerts.backend"
    label = "billing_alerts"
    verbose_name = "Billing alerts"

    def ready(self) -> None:
        from products.billing_alerts.backend import team_lifecycle  # noqa: F401, PLC0415
