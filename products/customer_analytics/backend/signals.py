"""Signal receivers for customer_analytics, wired from ``AppConfig.ready()``.

Kept import-light: receivers defer their heavy imports to call time so this module
costs nothing on the ``django.setup()`` path.
"""

from django.db.models.signals import pre_delete
from django.dispatch import receiver

from products.customer_analytics.backend.models import EventStream


@receiver(pre_delete, sender=EventStream, dispatch_uid="customer_analytics_event_stream_archive_destination")
def archive_destination_on_stream_delete(sender: type[EventStream], instance: EventStream, **kwargs) -> None:
    """Archive the stream's managed Slack destination whenever the stream row is deleted —
    API destroy, owner-deletion cascade, or team-deletion cascade — so no deletion path can
    leave a zombie HogFunction delivering to Slack."""
    # noqa comment: pulls the CDP facade (DRF serializers) — keep it off the setup path.
    from products.customer_analytics.backend.logic.event_stream_destination import (  # noqa: PLC0415
        archive_event_stream_destination,
    )

    archive_event_stream_destination(instance)
