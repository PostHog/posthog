from django.apps import AppConfig


class CanvasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.canvas.backend"
    label = "canvas"
    verbose_name = "Canvas"

    def ready(self) -> None:
        # Registers the artifact-delivery configuration system checks and the
        # search-index signal receivers.
        from posthog.models.file_system.unfiled_file_saver import register_mixin_model  # noqa: PLC0415

        from products.canvas.backend import checks, search_sync  # noqa: F401, PLC0415
        from products.canvas.backend.models import Canvas  # noqa: PLC0415

        register_mixin_model("canvas", Canvas)
