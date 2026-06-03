"""Django app configuration for annotations."""

from django.apps import AppConfig


class AnnotationsConfig(AppConfig):
    name = "products.annotations.backend"
    label = "annotations"

    def ready(self) -> None:
        # Connect the annotation activity-logging / analytics receivers at app-population. They used
        # to wire in via the viewset import; the lazy API router no longer pulls that, so connect here.
        from products.annotations.backend.api import annotation  # noqa: F401, PLC0415
