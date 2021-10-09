from typing import Any, Dict, List, Tuple

from django.db import connection
from django.db.models import F, OuterRef, Q
from django.db.models.expressions import Window
from django.db.models.functions import Lag

from posthog.models import Event, Team
from posthog.models.filters.path_filter import PathFilter
from posthog.queries.base import properties_to_Q
from posthog.utils import request_to_date_query

from .base import BaseQuery


class Paths(BaseQuery):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__()

    def _event_subquery(self, event: str, key: str):
        return Event.objects.filter(pk=OuterRef(event)).values(key)[:1]

    def _apply_start_point(
        self, start_comparator: str, query_string: str, sql_params: Tuple[str, ...], start_point: str
    ) -> Tuple[str, Tuple[str, ...]]:
        marked = "\
            SELECT *, CASE WHEN {} %s THEN timestamp ELSE NULL END as mark from ({}) as sessionified\
        ".format(
            start_comparator, query_string
        )

        marked_plus = "\
            SELECT *, MIN(mark) OVER (\
                    PARTITION BY person_id\
                    , session ORDER BY timestamp\
                    ) AS max from ({}) as marked order by session\
        ".format(
            marked
        )

        sessionified = "\
            SELECT * FROM ({}) as something where timestamp >= max \
        ".format(
            marked_plus
        )

        return sessionified, (start_point,) + sql_params

    def _add_elements(self, query_string: str) -> str:
        element = 'SELECT \'<\'|| e."tag_name" || \'> \'  || e."text" as tag_name_source, e."text" as text_source FROM "posthog_element" e JOIN \
                    ( SELECT group_id, MIN("posthog_element"."order") as minOrder FROM "posthog_element" GROUP BY group_id) e2 ON e.order = e2.minOrder AND e.group_id = e2.group_id where e.group_id = v2.group_id'
        element_group = 'SELECT g."id" as group_id FROM "posthog_elementgroup" g where v1."elements_hash" = g."hash"'
        sessions_sql = "SELECT * FROM ({}) as v1 JOIN LATERAL ({}) as v2 on true JOIN LATERAL ({}) as v3 on true".format(
            query_string, element_group, element
        )
        return sessions_sql

    def calculate_paths(self, filter: PathFilter, team: Team):
        date_query = request_to_date_query({"date_from": filter._date_from, "date_to": filter._date_to}, exact=False)
        resp = []
        prop_type = filter.prop_type
        event, event_filter = filter.target_event
        start_comparator = filter.comparator

        sessions = (
            Event.objects.add_person_id(team.pk)
            .filter(team=team, **(event_filter), **date_query)
            .filter(
                ~Q(event__in=["$autocapture", "$pageview", "$identify", "$pageleave", "$screen"])
                if event is None
                else Q()
            )
            .filter(properties_to_Q(filter.properties, team_id=team.pk) if filter and filter.properties else Q())
            .annotate(
                previous_timestamp=Window(
                    expression=Lag("timestamp", default=None),
                    partition_by=F("person_id"),
                    order_by=F("timestamp").asc(),
                )
            )
        )

        sessions_sql, sessions_sql_params = sessions.query.sql_with_params()

        events_notated = "\
        SELECT *, CASE WHEN EXTRACT('EPOCH' FROM (timestamp - previous_timestamp)) >= (60 * 30) OR previous_timestamp IS NULL THEN 1 ELSE 0 END AS new_session\
        FROM ({}) AS inner_sessions\
        ".format(
            sessions_sql
        )

        sessionified = "\
        SELECT events_notated.*, SUM(new_session) OVER (\
            ORDER BY person_id\
                    ,timestamp\
            ) AS session\
        FROM ({}) as events_notated\
        ".format(
            events_notated
        )

        if filter and filter.start_point:
            sessionified, sessions_sql_params = self._apply_start_point(
                start_comparator=start_comparator,
                query_string=sessionified,
                sql_params=sessions_sql_params,
                start_point=filter.start_point,
            )

        final = "\
        SELECT {} as path_type, id, sessionified.session\
            ,ROW_NUMBER() OVER (\
                    PARTITION BY person_id\
                    ,session ORDER BY timestamp\
                    ) AS event_number\
        FROM ({}) as sessionified\
        ".format(
            prop_type, sessionified
        )

        counts = "\
        SELECT event_number || '_' || path_type as target_event, id as target_id, LAG(event_number || '_' || path_type, 1) OVER (\
            PARTITION BY session\
            ) AS source_event , LAG(id, 1) OVER (\
            PARTITION BY session\
            ) AS source_id from \
        ({}) as final\
        where event_number <= 4\
        ".format(
            final
        )

        query = "\
        SELECT source_event, target_event, MAX(target_id), MAX(source_id), count(*) from ({}) as counts\
        where source_event is not null and target_event is not null\
        group by source_event, target_event order by count desc limit 20\
        ".format(
            counts
        )

        cursor = connection.cursor()
        cursor.execute(query, sessions_sql_params)
        rows = cursor.fetchall()

        for row in rows:
            resp.append(
                {"source": row[0], "target": row[1], "target_id": row[2], "source_id": row[3], "value": row[4],}
            )

        resp = sorted(resp, key=lambda x: x["value"], reverse=True)
        return resp

    def run(self, filter: PathFilter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        return self.calculate_paths(filter=filter, team=team)
