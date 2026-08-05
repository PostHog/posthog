from django.apps import AppConfig


class AutoresearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.autoresearch.backend"
    label = "autoresearch"

    def ready(self) -> None:
        from django.db.models.signals import post_save

        from products.autoresearch.backend.signals import on_task_run_saved

        # Lazy "app_label.Model" sender — keeps the tasks model off autoresearch's import path.
        post_save.connect(on_task_run_saved, sender="tasks.TaskRun", dispatch_uid="autoresearch.on_task_run_saved")
