"""Django app configuration for annotations."""

from django.apps import AppConfig


class AnnotationsConfig(AppConfig):
    name = "products.annotations.backend"
    label = "annotations"

    def ready(self) -> None:
        # Connect the annotation activity-logging / analytics receivers at app-population, from a
        # dedicated light module — importing the viewset module here would pull posthog.api
        # routing/utils (and posthog.schema with them) into django.setup() for every process type.
        from products.annotations.backend import activity_logging  # noqa: F401, PLC0415
