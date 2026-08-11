from django.apps import AppConfig


class CanvasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.canvas.backend"
    label = "canvas"
    verbose_name = "Canvas"

    def ready(self) -> None:
        # Registers the artifact-delivery configuration system checks.
        from products.canvas.backend import checks  # noqa: F401, PLC0415
