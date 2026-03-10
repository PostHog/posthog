import json
from datetime import timedelta

from django.utils.timezone import now

from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.client import sync_execute

_SPIKE_EVENT = "billing log"
_SPIKE_LOG_TYPE = "spike detected per customer"


def _spike_date(detected_spikes: list[dict], fallback: str) -> str:
    # The top-level spike_date property is often empty; the date lives inside each spike.
    if detected_spikes:
        return detected_spikes[0].get("date", fallback)
    return fallback


class SpikeAlertsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"

    def list(self, request: Request, **kw) -> Response:
        try:
            limit = min(int(request.GET.get("limit", 50)), 500)
            offset = int(request.GET.get("offset", 0))
        except (ValueError, TypeError):
            limit, offset = 50, 0

        start_date = now() - timedelta(days=30)

        # Spike alert events are written by an internal billing service into PostHog's
        # own project, not the customer's team. They are scoped by organization_id stored
        # in event properties rather than by team_id, so no team_id filter is applied.
        organization_id = str(self.team.organization_id)

        params = {
            "organization_id": organization_id,
            "start_date": start_date.strftime("%Y-%m-%d %H:%M:%S"),
            "event": _SPIKE_EVENT,
            "log_type": _SPIKE_LOG_TYPE,
            "limit": limit,
            "offset": offset,
        }

        rows = sync_execute(
            """
            SELECT uuid, properties, timestamp, count() OVER() AS total_count
            FROM events
            WHERE timestamp > %(start_date)s
              AND event = %(event)s
              AND JSONExtractString(properties, 'log_type') = %(log_type)s
              AND JSONExtractString(properties, 'organization_id') = %(organization_id)s
            ORDER BY timestamp DESC
            LIMIT %(limit)s
            OFFSET %(offset)s
            """,
            params,
        )

        total_count = rows[0][3] if rows else 0
        results = []
        for row_uuid, raw_properties, timestamp, _ in rows:
            props = json.loads(raw_properties) if isinstance(raw_properties, str) else raw_properties
            detected_spikes = props.get("detected_spikes", [])

            results.append(
                {
                    "id": str(row_uuid),
                    "detected_spikes": detected_spikes,
                    "spike_date": _spike_date(detected_spikes, props.get("spike_date", "")),
                    "detected_at": str(timestamp),
                }
            )

        return Response({"results": results, "count": total_count})
