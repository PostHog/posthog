"""The alert data the insight API embeds in its own response."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection
from typing import Any, cast

from django.db.models import Prefetch
from django.utils import timezone

from posthog.schema import NodeKind

from posthog.models.scoping import team_scope

from products.alerts.backend.models.alert import AlertConfiguration
from products.product_analytics.backend.facade.models import Insight


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


def native_insight_alerts(insights: Collection[Insight]) -> dict[int, list[AlertConfiguration]]:
    """Each insight's alerts with no insight row, as the alert API shows them, with one read per team.

    ``insight_alerts_prefetch`` loads only alerts with an insight row. A caller serializing a page of
    insights passes the whole page, so the page costs one read rather than one per insight.
    """
    # Deferred for the same import loop as `serialize_insight_alerts`.
    from products.alerts.backend.facade.platform import (  # noqa: PLC0415
        native_insight_alert_ids_by_insight,
        native_insight_alert_views,
    )
    from products.alerts.backend.presentation.views.alert import (  # noqa: PLC0415
        _show_platform_status,
        _show_platform_subscribers,
    )

    insight_ids_by_team: dict[int, set[int]] = defaultdict(set)
    for insight in insights:
        insight_ids_by_team[insight.team_id].add(insight.id)
    insights_by_id = {insight.id: insight for insight in insights}
    shown: dict[int, list[AlertConfiguration]] = {}
    now = timezone.now()
    for team_id, insight_ids in insight_ids_by_team.items():
        with team_scope(team_id):
            ids_by_insight = native_insight_alert_ids_by_insight(team_id, insight_ids)
            presented = AlertConfiguration.from_platform_views(
                native_insight_alert_views(team_id, [alert_id for ids in ids_by_insight.values() for alert_id in ids]),
                team_id=team_id,
            )
            alerts = list(presented.values())
            _show_platform_status(alerts, now=now)
            _show_platform_subscribers(alerts)
        for insight_id, alert_ids in ids_by_insight.items():
            # An alert moved to another insight between the two reads belongs to that insight now, which
            # the caller has not checked the reader may view.
            listed = [presented.get(alert_id) for alert_id in alert_ids]
            shown[insight_id] = [alert for alert in listed if alert is not None and alert.insight_id == insight_id]
            for alert in shown[insight_id]:
                # The caller's insight already carries what the alert serializer reads from it.
                alert.insight = insights_by_id[insight_id]
    return shown


def insight_alerts_hidden(insight: Insight, context: dict[str, Any]) -> bool:
    """Whether the insight API must embed none of the insight's alerts in this response."""
    # Alerts carry their creator's and subscribers' names and emails, which no viewer of a shared
    # link may receive, whether the shared page or the API with a sharing token serves them.
    if context.get("is_shared") or context.get("hide_extra_details"):
        return True
    # Deferred for the same import loop as `serialize_insight_alerts`.
    from products.alerts.backend.presentation.views.alert import _token_lacks_metrics_scope  # noqa: PLC0415

    # The alert API refuses a metrics alert's results to a token without a metrics scope.
    request = context.get("request")
    return (
        request is not None
        and insight.alertable_query_kind == NodeKind.METRICS_QUERY
        and _token_lacks_metrics_scope(request)
    )


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
