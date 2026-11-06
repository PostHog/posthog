from django.apps import AppConfig

from . import task_profiles


class AccountAuditsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.account_audits.backend"
    label = "account_audits"

    def ready(self) -> None:
        task_profiles.register()
