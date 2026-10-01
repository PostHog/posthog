from django.apps import AppConfig


class AccountAuditsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.account_audits.backend"
    label = "account_audits"

    def ready(self) -> None:
        # Deferred import: models aren't loadable at module import time, and ready() must stay light.
        from products.account_audits.backend import receivers  # noqa: PLC0415

        receivers.connect()
