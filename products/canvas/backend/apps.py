from django.apps import AppConfig


class CanvasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.canvas.backend"
    label = "canvas"
    verbose_name = "Canvas"

    def ready(self) -> None:
        # Registers the artifact-delivery configuration system checks and the
        # search-index signal receivers.
        from products.canvas.backend import checks, search_sync  # noqa: F401, PLC0415
