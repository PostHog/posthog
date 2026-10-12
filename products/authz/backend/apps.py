"""Django app configuration for authz."""

from django.apps import AppConfig


class AuthzConfig(AppConfig):
    name = "products.authz.backend"
    label = "authz"

    def ready(self) -> None:
        from . import signals  # noqa: F401, PLC0415 -- register lightweight receivers without loading the SDK
        from .tasks import tasks  # noqa: F401, PLC0415 -- register the task in web and worker processes
