import json
from datetime import timedelta

from django.utils.timezone import now

from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.client import sync_execute


class IngestionWarningsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"

    def list(self, request: Request, **kw) -> Response:
        start_date = now() - timedelta(days=30)
        query = """
            SELECT
                type,
                count(details) as total_count,
                arraySlice(groupArray((details, timestamp)), 1, 50) as top_50_recent_examples,
                groupUniqArray((day_count, day)) as daily_counts
            FROM
                (
                    SELECT
                        type,
                        details,
                        timestamp,
                        toDate(timestamp) as day,
                        count(details) OVER (PARTITION BY type, toDate(timestamp)) as day_count
                    FROM
                        ingestion_warnings
                    WHERE
                        team_id = %(team_id)s
                        AND timestamp > %(start_date)s
                        AND (
                    %(search)s IS NULL OR positionUTF8(details, %(search)s) > 0 OR positionUTF8(type, %(search)s) > 0
                        )
                    ORDER BY
                        type,
                        timestamp DESC
                )
            GROUP BY
                type
        """
        warning_events = sync_execute(
            query,
            {
                "team_id": self.team_id,
                "start_date": start_date.strftime("%Y-%m-%d %H:%M:%S"),
                "search": request.GET.get("q", None),
            },
        )

        return Response({"results": _calculate_summaries(warning_events)})


def _calculate_summaries(warning_events):
    summaries = {}
    for warning_type, count, examples, sparkline in warning_events:
        summaries[warning_type] = {
            "type": warning_type,
            "lastSeen": examples[0][1] if examples else None,
            "sparkline": sparkline,
            "warnings": [
                {
                    "type": warning_type,
                    "timestamp": timestamp,
                    "details": json.loads(details),
                }
                for details, timestamp in examples
            ],
            "count": count,
        }

    return sorted(summaries.values(), key=lambda summary: summary["lastSeen"], reverse=True)
