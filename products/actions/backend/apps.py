from django.apps import AppConfig


class ActionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.actions.backend"
    label = "actions"

    def ready(self) -> None:
        # Connect the action activity-log receiver at app-population, from a dedicated light
        # module. It must not live in the viewset module: that pulls posthog.api routing/utils
        # (and posthog.schema with them) into django.setup() for every process type.
        from posthog.models.file_system.unfiled_file_saver import register_mixin_model  # noqa: PLC0415
        from posthog.models.resource_transfer.registered_models import register_model  # noqa: PLC0415

        from products.actions.backend import activity_logging  # noqa: F401, PLC0415
        from products.actions.backend.models.action import Action  # noqa: PLC0415

        # Core keeps per-model registries for unfiled items and resource transfer. Registering from here
        # keeps those modules from importing this product's model.
        register_mixin_model("action", Action)
        register_model("Action", Action)
