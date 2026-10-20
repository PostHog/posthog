from django.apps import AppConfig


class ContextLayerAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.context_layer.backend"
    label = "context_layer"
    verbose_name = "Context layer"

    def ready(self) -> None:
        from products.context_layer.backend import task_profiles  # noqa: PLC0415
        from products.tasks.backend.facade.profiles import register_task_profiles  # noqa: PLC0415

        register_task_profiles(task_profiles.PROFILES)
