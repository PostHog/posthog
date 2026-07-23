from django.apps import AppConfig


class AutoresearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.autoresearch.backend"
    label = "autoresearch"

    def ready(self) -> None:
        # Import here (after the app registry is fully initialised) to avoid
        # importing TaskRun at module level before Django is ready.
        from django.db.models.signals import post_save

        from products.autoresearch.backend.signals import on_task_run_saved
        from products.tasks.backend.models import TaskRun

        post_save.connect(on_task_run_saved, sender=TaskRun, dispatch_uid="autoresearch.on_task_run_saved")
