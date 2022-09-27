import json

from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.client import sync_execute


class IngestionWarningsViewSet(StructuredViewSetMixin, viewsets.ViewSet):
    def list(self, request: Request, **kw) -> Response:
        warning_events = sync_execute(
            """
            SELECT timestamp, properties
            FROM events
            WHERE team_id = %(team_id)s
              AND event = '$$ingestion_warning'
              AND timestamp > now() - INTERVAL 30 day
            ORDER BY timestamp DESC
        """,
            {"team_id": self.team_id},
        )

        return Response({"results": _calculate_summaries(warning_events)})


def _calculate_summaries(warning_events):
    summaries = {}
    for timestamp, properties_string in warning_events:
        properties = json.loads(properties_string)
        try:
            warning_type = properties["type"]
            warning_details = properties["details"]

            if warning_type not in summaries:
                summaries[warning_type] = {"type": warning_type, "lastSeen": timestamp, "warnings": [], "count": 0}

            summaries[warning_type]["warnings"].append(
                {"type": warning_type, "timestamp": timestamp, "details": warning_details}
            )
            summaries[warning_type]["count"] += 1
        except:
            # Ignore invalid events
            pass

    return list(sorted(summaries.values(), key=lambda summary: summary["lastSeen"], reverse=True))
