import re
from typing import Optional

from dateutil.relativedelta import relativedelta
from django.utils.timezone import now
from loginas.utils import is_impersonated_session
from rest_framework import exceptions, viewsets
from rest_framework.response import Response

from posthog.client import sync_execute
from posthog.cloud_utils import is_cloud
from posthog.settings.base_variables import DEBUG
from posthog.settings.data_stores import CLICKHOUSE_CLUSTER


class DebugCHQueries(viewsets.ViewSet):
    """
    List recent CH queries initiated by this user.
    """

    def _get_path(self, query: str) -> Optional[str]:
        try:
            return re.findall(r"request:([a-zA-Z0-9-_@]+)", query)[0].replace("_", "/")
        except:
            return None

    def list(self, request):
        if not (request.user.is_staff or DEBUG or is_impersonated_session(request) or not is_cloud()):
            raise exceptions.PermissionDenied("You're not allowed to see queries.")

        response = sync_execute(
            """
            SELECT
                query_id,
                argMax(query, type) AS query,
                argMax(query_json, type) AS query_json,
                argMax(query_start_time, type) AS query_start_time,
                argMax(exception, type) AS exception,
                argMax(query_duration_ms, type) AS query_duration_ms,
                argMax(ProfileEvents, type) as profile_events,
                max(type) AS status
            FROM (
                SELECT
                    query_id, query, query_start_time, exception, query_duration_ms, toInt8(type) AS type,
                    JSONExtractRaw(log_comment, 'query') as query_json,
                    ProfileEvents
                FROM clusterAllReplicas(%(cluster)s, system, query_log)
                WHERE
                    query LIKE %(query)s AND
                    query NOT LIKE %(not_query)s AND
                    event_time > %(start_time)s AND
                    is_initial_query
                ORDER BY query_start_time DESC
                LIMIT 100
            )
            GROUP BY query_id
            ORDER BY query_start_time DESC""",
            {
                "query": f"/* user_id:{request.user.pk} %",
                "start_time": (now() - relativedelta(minutes=10)).timestamp(),
                "not_query": "%request:_api_debug_ch_queries_%",
                "cluster": CLICKHOUSE_CLUSTER,
            },
        )
        return Response(
            [
                {
                    "query_id": resp[0],
                    "query": resp[1],
                    "queryJson": resp[2],
                    "timestamp": resp[3],
                    "exception": resp[4],
                    "execution_time": resp[5],
                    "profile_events": resp[6],
                    "status": resp[7],
                    "path": self._get_path(resp[1]),
                }
                for resp in response
            ]
        )
