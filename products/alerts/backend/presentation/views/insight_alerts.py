"""The alert data the insight API embeds in its own response."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any, cast

from django.db.models import Prefetch

from products.alerts.backend.models.alert import AlertConfiguration


def insight_alerts_prefetch(to_attr: str) -> Prefetch:
    """A ``Prefetch`` loading an insight's alerts in the shape ``serialize_insight_alerts`` needs.

    Callers add it to their insight queryset and read the alerts back off ``to_attr``. The
    select_related/prefetch_related shape belongs here because it follows AlertSerializer:
    that serializer emits threshold and subscribed_users per alert, so without them every
    alert in the response costs two extra queries.
    """
    # Sets no team filter of its own: the prefetch is scoped by the insight queryset it is
    # attached to, and an alert always belongs to its insight's team.
    # nosemgrep: idor-lookup-without-team
    queryset = AlertConfiguration.objects.select_related("created_by", "threshold").prefetch_related("subscribed_users")
    return Prefetch("alertconfiguration_set", queryset=queryset, to_attr=to_attr)


def serialize_insight_alerts(alerts: Collection[AlertConfiguration], context: dict[str, Any]) -> list[dict[str, Any]]:
    """Render an insight's alerts for the insight API response.

    The insight API prefetches the alerts so the render costs no extra query, then hands them
    back here — the alert JSON shape is this product's to define, not product_analytics'.
    ``context`` is the calling serializer's DRF context.
    """
    # Deferred: the insight API imports this module and `alert` imports the insight API, so
    # the three form an import loop that only a deferred edge keeps open.
    from products.alerts.backend.presentation.views.alert import AlertSerializer  # noqa: PLC0415

    # `many=True` yields a ReturnList; the DRF stubs type `.data` as ReturnDict either way.
    return cast(list[dict[str, Any]], AlertSerializer(alerts, many=True, context=context).data)
