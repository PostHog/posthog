from django.apps import AppConfig
from django.db.models.signals import post_save


class AutoresearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.autoresearch.backend"
    label = "autoresearch"

    def ready(self) -> None:
        # Deferred because the receiver module imports models, which are not usable
        # at the time this module itself is imported.
        from products.autoresearch.backend.signals import on_task_run_saved  # noqa: PLC0415

        # Lazy "app_label.Model" sender keeps the tasks model off autoresearch's import path.
        post_save.connect(on_task_run_saved, sender="tasks.TaskRun", dispatch_uid="autoresearch.on_task_run_saved")
