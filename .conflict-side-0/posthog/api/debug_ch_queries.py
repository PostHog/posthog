import re
import json
from datetime import UTC, datetime, timedelta
from typing import Optional

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta
from loginas.utils import is_impersonated_session
from rest_framework import exceptions, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.clickhouse.client import sync_execute
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

    def hourly_stats(self, insight_id: str):
        params = {
            "insight_id": insight_id,
            "start_time": (datetime.now() - timedelta(days=14)).timestamp(),
            "not_query": "%request:_api_debug_ch_queries_%",
            "cluster": CLICKHOUSE_CLUSTER,
        }

        sql_query = """
            SELECT
                hour,
                sum(successful_queries) AS successful_queries,
                sum(exceptions) AS exceptions,
                avg(avg_response_time_ms) AS avg_response_time_ms
            FROM (
                SELECT
                    toStartOfHour(query_start_time) AS hour,
                    countIf(exception = '') AS successful_queries,
                    countIf(exception != '') AS exceptions,
                    avg(query_duration_ms) AS avg_response_time_ms
                FROM (
                    SELECT
                        query_id, query, query_start_time, exception, query_duration_ms, toInt8(type) AS type,
                        ProfileEvents, log_comment
                    FROM clusterAllReplicas(%(cluster)s, system, query_log)
                    WHERE
                        JSONExtractString(log_comment, 'insight_id') = %(insight_id)s AND
                        event_time > %(start_time)s AND
                        query NOT LIKE %(not_query)s AND
                        is_initial_query
                    ORDER BY query_start_time DESC
                    LIMIT 100
                    SETTINGS skip_unavailable_shards=1
                )
                GROUP BY hour
                ORDER BY hour
            )
            GROUP BY hour
            ORDER BY hour
        """

        response = sync_execute(sql_query, params)
        return [
            {
                "hour": resp[0],
                "successful_queries": resp[1],
                "exceptions": resp[2],
                "avg_response_time_ms": resp[3],
            }
            for resp in response
        ]

    def stats(self, insight_id: str):
        params = {
            "insight_id": insight_id,
            "start_time": (datetime.now(UTC) - timedelta(days=14)).timestamp(),
            "cluster": CLICKHOUSE_CLUSTER,
        }

        sql_query = """
            SELECT
                count(*) AS total_queries,
                countIf(exception != '') AS total_exceptions,
                avg(query_duration_ms) AS average_query_duration_ms,
                max(query_duration_ms) AS max_query_duration_ms,
                (countIf(exception != '') / count(*)) * 100 AS exception_percentage
            FROM (
                SELECT
                    query_id, query, query_start_time, exception, query_duration_ms,
                    JSONExtractString(log_comment, 'insight_id') AS extracted_insight_id
                FROM clusterAllReplicas(%(cluster)s, system, query_log)
                WHERE
                    JSONExtractRaw(log_comment, 'insight_id') = %(insight_id)s AND
                    event_time > %(start_time)s AND
                    is_initial_query

                SETTINGS skip_unavailable_shards=1
            )
        """

        response = sync_execute(sql_query, params)
        return {
            "total_queries": response[0][0],
            "total_exceptions": response[0][1],
            "average_query_duration_ms": response[0][2],
            "max_query_duration_ms": response[0][3],
            "exception_percentage": response[0][4],
        }

    def queries(self, request: Request, insight_id: Optional[str] = None):
        params: dict = {
            "not_query": "%request:_api_debug_ch_queries_%",
            "cluster": CLICKHOUSE_CLUSTER,
        }
        limit_clause = ""

        if insight_id:
            where_clause = "JSONExtractRaw(log_comment, 'insight_id') = %(insight_id)s"
            params["insight_id"] = insight_id
            limit_clause = "LIMIT 10"
        else:
            where_clause = "query LIKE %(query)s AND event_time > %(start_time)s"
            params["query"] = f"/* user_id:{request.user.pk} %"
            params["start_time"] = (now() - relativedelta(minutes=10)).timestamp()

        response = sync_execute(
            f"""
            SELECT
                query_id,
                argMax(query, type) AS query,
                argMax(query_start_time, type) AS query_start_time,
                argMax(exception, type) AS exception,
                argMax(query_duration_ms, type) AS query_duration_ms,
                argMax(ProfileEvents, type) as profile_events,
                argMax(log_comment, type) AS log_comment,
                max(type) AS status
            FROM (
                SELECT
                    query_id, query, query_start_time, exception, query_duration_ms, toInt8(type) AS type,
                    ProfileEvents, log_comment
                FROM clusterAllReplicas(%(cluster)s, system, query_log)
                WHERE
                    {where_clause} AND
                    query NOT LIKE %(not_query)s AND
                    is_initial_query
                ORDER BY query_start_time DESC
                LIMIT 100

                SETTINGS skip_unavailable_shards=1
            )
            GROUP BY query_id
            ORDER BY query_start_time DESC
            {limit_clause}
            """,
            params,
        )
        return [
            {
                "query_id": resp[0],
                "query": resp[1],
                "timestamp": resp[2],
                "exception": resp[3],
                "execution_time": resp[4],
                "profile_events": resp[5],
                "logComment": json.loads(resp[6]),
                "status": resp[7],
                "path": self._get_path(resp[1]),
            }
            for resp in response
        ]

    def list(self, request):
        if not (request.user.is_staff or DEBUG or is_impersonated_session(request) or not is_cloud()):
            raise exceptions.PermissionDenied("You're not allowed to see queries.")

        insight_id = request.query_params.get("insight_id")
        queries = self.queries(request, insight_id)
        response = {"queries": queries}
        if insight_id:
            response["stats"] = self.stats(insight_id)
            response["hourly_stats"] = self.hourly_stats(insight_id)
        return Response(response)
