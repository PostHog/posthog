import json
from datetime import timedelta

from django.utils.timezone import now
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.client import sync_execute


class IngestionWarningsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "not_supported"

    def list(self, request: Request, **kw) -> Response:
        start_date = now() - timedelta(days=30)
        warning_events = sync_execute(
            """
            SELECT type, timestamp, details
            FROM ingestion_warnings
            WHERE team_id = %(team_id)s
              AND timestamp > %(start_date)s
            ORDER BY timestamp DESC
        """,
            {
                "team_id": self.team_id,
                "start_date": start_date.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )

        return Response({"results": _calculate_summaries(warning_events)})


def _calculate_summaries(warning_events):
    summaries = {}
    for warning_type, timestamp, details in warning_events:
        details = json.loads(details)
        if warning_type not in summaries:
            summaries[warning_type] = {
                "type": warning_type,
                "lastSeen": timestamp,
                "warnings": [],
                "count": 0,
            }

        summaries[warning_type]["warnings"].append({"type": warning_type, "timestamp": timestamp, "details": details})
        summaries[warning_type]["count"] += 1

    return list(sorted(summaries.values(), key=lambda summary: summary["lastSeen"], reverse=True))
