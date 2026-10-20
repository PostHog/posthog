from django.apps import AppConfig


class AccountAuditsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.account_audits.backend"
    label = "account_audits"

    def ready(self) -> None:
        from products.account_audits.backend import task_profiles  # noqa: PLC0415
        from products.tasks.backend.facade.profiles import register_task_profiles  # noqa: PLC0415

        register_task_profiles(task_profiles.PROFILES)
