from typing import Any, cast

from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import StructuredViewSetMixin
from posthog.clickhouse.client import sync_execute
from posthog.models import User


class PersonCommunicationViewSet(StructuredViewSetMixin, viewsets.GenericViewSet):
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        bug_report_uuid = request.GET.get("bug_report_uuid")

        if not bug_report_uuid:
            raise ValidationError("bug_report_uuid is required")

        user = cast(User, request.user)

        if not user.team or user.current_team_id != self.team_id:
            return Response({"detail": "You do not have access to this team"}, status=403)

        slow_query = f"""
        select JSONExtractString(properties, 'bug_report_uuid'), event, JSONExtractString(properties, 'from'),
         JSONExtractString(properties, 'to'), JSONExtractString(properties, 'subject'),
         JSONExtractString(properties, 'body_plain'), JSONExtractString(properties, 'body_html'),
         JSONExtractString(properties, 'email'), JSONExtractString(properties, '$bug'), timestamp
        from events
        prewhere team_id = %(team_id)s
        and timestamp <= now() + INTERVAL 1 DAY
        and timestamp >= now() - INTERVAL 7 DAY
        and event in ('$communication_email_sent', '$communication_email_received', '$communication_note_saved', '$bug_report')
        and (JSONExtractString(properties, 'bug_report_uuid') = %(bug_report_uuid)s or uuid = %(bug_report_uuid)s)
        order by timestamp DESC
        """

        results = sync_execute(slow_query, {"team_id": self.team.pk, "bug_report_uuid": bug_report_uuid})

        column_names = [
            "bug_report_uuid",
            "event",
            "from",
            "to",
            "subject",
            "body_plain",
            "body_html",
            "email",
            "bug_report",
            "timestamp",
        ]
        columnized_results = [dict(zip(column_names, res)) for res in results]

        if columnized_results:
            # the last event is always the bug report
            bug_report = columnized_results[-1]
            reporter_email = bug_report.get("email", "unknown reporter")

            corrected_results = []
            for x in columnized_results:
                bug_report = x.pop("bug_report", None)
                if bug_report:
                    x["body_plain"] = bug_report
                corrected_results.append({**x, "email": reporter_email})

            return Response({"results": corrected_results})
        else:
            return Response({"results": []})
