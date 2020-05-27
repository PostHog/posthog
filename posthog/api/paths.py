from rest_framework import viewsets
from rest_framework.response import Response
from posthog.models import Event, Filter
from posthog.utils import request_to_date_query
from django.db.models import OuterRef
from django.db import connection
from typing import Optional

from django.db.models.expressions import Window
from django.db.models.functions import Lag
from django.db.models import F, Q
from django.db import connection

import json

# At the moment, paths don't support users changing distinct_ids midway through.
# See: https://github.com/PostHog/posthog/issues/185
class PathsViewSet(viewsets.ViewSet):
    def _event_subquery(self, event: str, key: str):
        return Event.objects.filter(pk=OuterRef(event)).values(key)[:1]
    
    def _determine_path_type(self, request):
        requested_type = request.GET.get('type', None)
        
        # Default
        event: Optional[str] = "$pageview"
        event_filter = {"event":event}
        path_type = "properties->> \'$current_url\'"

        # determine requested type
        if requested_type:
            if requested_type == "$screen":
                event = "$screen"
                event_filter = {"event":event}
                path_type = "properties->> \'$screen_name\'"
            elif requested_type == "$autocapture":
                event = "$autocapture"
                event_filter = {"event":event}
                path_type = "tag_name_source"
            elif requested_type == "custom_event":
                event = None
                event_filter = {'event__regex':'^[^\$].*'}
                path_type = "event"
        return event, path_type, event_filter

    # FIXME: Timestamp is timezone aware timestamp, date range uses naive date.
    # To avoid unexpected results should convert date range to timestamps with timezone.
    def list(self, request):
        team = request.user.team_set.get()
        resp = []
        date_query = request_to_date_query(request.GET)
        event, path_type, event_filter = self._determine_path_type(request)
        properties = request.GET.get('properties')

        sessions = Event.objects.add_person_id(team.pk).filter(
                team=team,
                **(event_filter), #anything without $ (default)
                **date_query
            )\
            .filter(Filter(data={'properties': json.loads(properties)}).properties_to_Q() if properties else Q())\
            .annotate(previous_timestamp=Window(
                expression=Lag('timestamp', default=None),
                partition_by=F('distinct_id'),
                order_by=F('timestamp').asc()
            ))

        sessions_sql, sessions_sql_params = sessions.query.sql_with_params()

        if event == "$autocapture":
                element = 'SELECT \'<\'|| e."tag_name" || \'> \'  || e."text" as tag_name_source, e."text" as text_source FROM "posthog_element" e JOIN \
                    ( SELECT group_id, MIN("posthog_element"."order") as minOrder FROM "posthog_element" GROUP BY group_id) e2 ON e.order = e2.minOrder AND e.group_id = e2.group_id where e.group_id = v2.group_id'
                element_group = 'SELECT g."id" as group_id FROM "posthog_elementgroup" g where v1."elements_hash" = g."hash"'
                sessions_sql = 'SELECT * FROM ({}) as v1 JOIN LATERAL ({}) as v2 on true JOIN LATERAL ({}) as v3 on true'.format(sessions_sql, element_group, element)

        cursor = connection.cursor()
        cursor.execute('\
        SELECT source_event, target_event, MAX(target_id), MAX(source_id), count(*) from (\
            SELECT event_number || \'_\' || path_type as target_event, id as target_id, LAG(event_number || \'_\' || path_type, 1) OVER (\
                            PARTITION BY session\
                            ) AS source_event , LAG(id, 1) OVER (\
                            PARTITION BY session\
                            ) AS source_id from \
        (\
            SELECT {} as path_type, id, sessionified.session\
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
                'source': row[0],
                'target': row[1],
                'target_id': row[2],
                'source_id': row[3],
                'value': row[4]
            })

        
        resp = sorted(resp, key=lambda x: x['value'], reverse=True)
        return Response(resp)
