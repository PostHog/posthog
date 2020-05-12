from rest_framework import viewsets
from rest_framework.response import Response
from posthog.models import Event, PersonDistinctId, Team, ElementGroup, Element
from posthog.utils import request_to_date_query, dict_from_cursor_fetchall
from django.db.models import Subquery, OuterRef, Count, QuerySet
from django.db import connection
from typing import List, Optional

from django.db.models.expressions import Window
from django.db.models.functions import Lag
from django.db.models import F
from django.db import connection

# At the moment, paths don't support users changing distinct_ids midway through.
# See: https://github.com/PostHog/posthog/issues/185
class PathsViewSet(viewsets.ViewSet):
    def _event_subquery(self, event: str, key: str):
        return Event.objects.filter(pk=OuterRef(event)).values(key)[:1]
    
    def _determine_path_type(self, request):
        requested_type = request.GET.get('type', None)
        
        # Default
        event: Optional[str] = "$pageview"
        path_type = "properties->> \'$current_url\'"

        # determine requested type
        if requested_type:
            if requested_type == "$screen":
                event = "$screen"
                path_type = "properties->> \'$screen\'"
            elif requested_type == "$autocapture":
                event = "$autocapture"
                path_type = "elements_hash"
            elif requested_type == "custom_event":
                event = None
                path_type = "event"
        return event, path_type

    # FIXME: Timestamp is timezone aware timestamp, date range uses naive date.
    # To avoid unexpected results should convert date range to timestamps with timezone.
    def list(self, request):
        team = request.user.team_set.get()
        resp = []
        date_query = request_to_date_query(request.GET)
        event, path_type = self._determine_path_type(request)

        sessions = Event.objects.filter(
                team=team,
                **({"event":event} if event else {'event__regex':'^[^\$].*'}), #anything without $ (default)
                **date_query
            )\
            .annotate(previous_timestamp=Window(
                expression=Lag('timestamp', default=None),
                partition_by=F('distinct_id'),
                order_by=F('timestamp').asc()
            ))

        sessions_sql, sessions_sql_params = sessions.query.sql_with_params()

        cursor = connection.cursor()
        cursor.execute('\
        SELECT source_event, target_event, count(*) from (\
            SELECT event_number || \'_\' || path_type as target_event,LAG(event_number || \'_\' || path_type, 1) OVER (\
                            PARTITION BY session\
                            ) AS source_event from \
        (\
            SELECT {} as path_type, sessionified.session\
                ,ROW_NUMBER() OVER (\
                        PARTITION BY distinct_id\
                        ,session ORDER BY timestamp\
                        ) AS event_number\
        FROM (\
            SELECT events_notated.*, SUM(new_session) OVER (\
                ORDER BY distinct_id\
                        ,timestamp\
                ) AS session\
            FROM (\
                SELECT *, CASE WHEN EXTRACT(\'EPOCH\' FROM (timestamp - previous_timestamp)) >= (60 * 30) OR previous_timestamp IS NULL THEN 1 ELSE 0 END AS new_session\
                FROM ({}) AS inner_sessions \
            ) as events_notated \
        ) as sessionified\
        ) as final\
        where event_number <= 4\
        ) as counts\
        where source_event is not null and target_event is not null and SUBSTRING(source_event, 3) != SUBSTRING(target_event, 3)\
        group by source_event, target_event order by count desc limit 15\
        '.format(path_type, sessions_sql), sessions_sql_params)
        rows = cursor.fetchall()

        for row in rows:
            resp.append({
                'sourceLabel': row[0],
                'targetLabel': row[1],
                'source': row[0],
                'target': row[1],
                'value': row[2]
            })

        
        resp = sorted(resp, key=lambda x: x['value'], reverse=True)
        return Response(resp)
