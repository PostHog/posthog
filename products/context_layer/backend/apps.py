from django.apps import AppConfig


class ContextLayerAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.context_layer.backend"
    label = "context_layer"
    verbose_name = "Context layer"
