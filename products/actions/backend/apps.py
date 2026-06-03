from django.apps import AppConfig


class ActionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.actions.backend"
    label = "actions"

    def ready(self) -> None:
        # Connect the action activity-log receiver at app-population. It used to wire in as an
        # import side effect of the viewset module; the lazy API router no longer pulls that, so a
        # process that never builds the router (celery, temporal, migrate) would drop audit logs on
        # action writes. The module is light (no heavy deps), so importing it here stays cheap.
        from products.actions.backend.api import action  # noqa: F401, PLC0415
