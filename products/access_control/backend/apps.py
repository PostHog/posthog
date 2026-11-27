"""Django app configuration for access_control."""

from typing import TYPE_CHECKING

from django.apps import AppConfig

if TYPE_CHECKING:
    from celery import Celery


def _register_periodic_tasks(sender: "Celery", **_kwargs: object) -> None:
    from posthog.tasks.scheduled import add_periodic_task_with_expiry  # noqa: PLC0415

    from products.access_control.backend.tasks.schedules import GITHUB_ROLE_SYNC_CRONTAB  # noqa: PLC0415
    from products.access_control.backend.tasks.tasks import sync_all_organization_github_roles  # noqa: PLC0415

    add_periodic_task_with_expiry(
        sender,
        GITHUB_ROLE_SYNC_CRONTAB,
        sync_all_organization_github_roles.s(),
        name="sync github organization team roles",
    )


class AccessControlConfig(AppConfig):
    name = "products.access_control.backend"
    label = "access_control"

    def ready(self) -> None:
        # Connect the restriction-cache invalidation receivers at app-population. They used to be
        # wired as a side effect of the HogQL printer importing this module at django.setup();
        # that import is now deferred to compile time, so the wiring must happen here or the
        # receivers connect in no process and cache invalidation silently stops.
        # Rules are written from the API and from product code in workers, so the audit
        # receiver must connect in every process.
        from celery.signals import import_modules  # noqa: PLC0415

        from posthog.celery import app as celery_app  # noqa: PLC0415

        from products.access_control.backend import (
            activity_logging,  # noqa: F401, PLC0415
            property_access_control,  # noqa: F401, PLC0415
        )

        import_modules.connect(_register_periodic_tasks, sender=celery_app, weak=False)
