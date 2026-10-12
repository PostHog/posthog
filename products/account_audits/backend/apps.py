from django.apps import AppConfig


class AccountAuditsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.account_audits.backend"
    label = "account_audits"

    def ready(self) -> None:
        from products.account_audits.backend import receivers  # noqa: PLC0415 — registers receivers after apps load

        receivers.connect()
