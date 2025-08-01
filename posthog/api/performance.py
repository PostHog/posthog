from datetime import datetime
from typing import Any

from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.client import sync_execute
from posthog.permissions import TeamMemberAccessPermission
from posthog.utils import relative_date_parse


class PerformanceQuerySerializer(serializers.Serializer):
    """Serializer for performance event query parameters."""
    date_from = serializers.CharField(required=False, default="-7d")
    date_to = serializers.CharField(required=False, default=None)
    session_id = serializers.CharField(required=False)
    url_filter = serializers.CharField(required=False)
    initiator_type = serializers.CharField(required=False)
    response_status = serializers.IntegerField(required=False)
    limit = serializers.IntegerField(required=False, default=100, max_value=1000)
    offset = serializers.IntegerField(required=False, default=0)


class PerformanceViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """API endpoint for querying network performance data from ClickHouse."""
    permission_classes = [TeamMemberAccessPermission]

    def list(self, request: Request, **kwargs) -> Response:
        """List performance events with filtering support."""
        serializer = PerformanceQuerySerializer(data=request.GET)
        serializer.is_valid(raise_exception=True)

        team = self.team
        data = serializer.validated_data
        date_from, date_to = self._parse_date_range(data)

        conditions = [
            "team_id = %(team_id)s",
            "timestamp >= %(date_from)s",
            "timestamp <= %(date_to)s"
        ]
        params = {
            "team_id": team.id,
            "date_from": date_from,
            "date_to": date_to,
            "limit": data["limit"],
            "offset": data["offset"]
        }

        if data.get("session_id"):
            conditions.append("session_id = %(session_id)s")
            params["session_id"] = data["session_id"]

        if data.get("url_filter"):
            conditions.append("name ILIKE %(url_filter)s")
            params["url_filter"] = f"%{data['url_filter']}%"

        if data.get("initiator_type"):
            conditions.append("initiator_type = %(initiator_type)s")
            params["initiator_type"] = data["initiator_type"]

        if data.get("response_status"):
            conditions.append("response_status = %(response_status)s")
            params["response_status"] = data["response_status"]

        where_clause = " AND ".join(conditions)

        # Using direct ClickHouse query for simple filtering - similar to app_metrics2.py pattern
        # This avoids the overhead of a full HogQL QueryRunner for straightforward SELECT operations
        query = f"""
        SELECT
            uuid,
            session_id,
            timestamp,
            name,
            entry_type,
            duration,
            response_status,
            transfer_size,
            initiator_type,
            current_url
        FROM performance_events
        WHERE {where_clause}
        ORDER BY timestamp DESC
        LIMIT %(limit)s
        OFFSET %(offset)s
        """

        results = sync_execute(query, params)

        events = []
        for row in results:
            events.append({
                "uuid": row[0],
                "session_id": row[1],
                "timestamp": row[2],
                "name": row[3],
                "entry_type": row[4],
                "duration": row[5],
                "response_status": row[6],
                "transfer_size": row[7],
                "initiator_type": row[8],
                "current_url": row[9],
            })

        return Response({
            "results": events,
            "count": len(events),
            "next": len(events) == data["limit"]
        })

    def _parse_date_range(self, data: dict[str, Any]) -> tuple[datetime, datetime]:
        """Parse date range from query parameters."""
        date_to = data.get("date_to")
        if date_to:
            date_to = relative_date_parse(date_to, self.team.timezone_info)
        else:
            from django.utils import timezone
            date_to = timezone.now()

        date_from = relative_date_parse(data["date_from"], self.team.timezone_info)
        return date_from, date_to

