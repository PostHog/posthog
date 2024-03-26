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
                query_id, argMax(query, type), argMax(query_start_time, type), argMax(exception, type),
                argMax(query_duration_ms, type), max(type) AS status
            FROM (
                SELECT
                    query_id, query, query_start_time, exception, query_duration_ms, toInt8(type) AS type
                FROM clusterAllReplicas(%(cluster)s, system, query_log)
                WHERE
                    query LIKE %(query)s AND
                    query NOT LIKE %(not_query)s AND
                    query_start_time > %(start_time)s
                ORDER BY query_start_time desc
                LIMIT 100
            )
            GROUP BY query_id""",
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
                    "timestamp": resp[2],
                    "exception": resp[3],
                    "execution_time": resp[4],
                    "status": resp[5],
                    "path": self._get_path(resp[1]),
                }
                for resp in response
            ]
        )
