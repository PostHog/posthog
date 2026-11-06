from django.apps import AppConfig

from . import task_profiles


class ContextLayerAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.context_layer.backend"
    label = "context_layer"
    verbose_name = "Context layer"

    def ready(self) -> None:
        task_profiles.register()
