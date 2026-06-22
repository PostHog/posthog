from django.apps import AppConfig


class ActionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.actions.backend"
    label = "actions"

    def ready(self) -> None:
        # Connect the action activity-log receiver at app-population, from a dedicated light
        # module. It must not live in the viewset module: that pulls posthog.api routing/utils
        # (and posthog.schema with them) into django.setup() for every process type.
        from products.actions.backend import activity_logging  # noqa: F401, PLC0415
