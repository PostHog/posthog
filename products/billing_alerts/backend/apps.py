from django.apps import AppConfig


class BillingAlertsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.billing_alerts.backend"
    label = "billing_alerts"
    verbose_name = "Billing alerts"
