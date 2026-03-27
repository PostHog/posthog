import re
import json
import time
import logging
from datetime import UTC, datetime, timedelta
from typing import Optional

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta
from loginas.utils import is_impersonated_session
from rest_framework import exceptions, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload, get_client_from_pool
from posthog.cloud_utils import is_cloud
from posthog.settings.base_variables import DEBUG
from posthog.settings.data_stores import CLICKHOUSE_CLUSTER
from posthog.utils import generate_short_id

logger = logging.getLogger(__name__)


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

        # nosemgrep: clickhouse-fstring-param-audit - where_clause/limit_clause from internal builder
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
                "logComment": json.loads(resp[6]) if resp[6] else {},
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

    @action(detail=False, methods=["POST"])
    def profile(self, request):
        if not request.user.is_staff:
            raise exceptions.PermissionDenied("Only staff users can profile queries.")

        query = request.data.get("query", "").strip()
        if not query:
            raise exceptions.ValidationError("No query provided.")

        profile_query_id = f"profile_{generate_short_id()}"

        start_time = time.monotonic()
        try:
            with get_client_from_pool(workload=Workload.OFFLINE, readonly=False) as client:
                client.execute(
                    query,
                    settings={
                        "readonly": 2,
                        "query_profiler_cpu_time_period_ns": 10_000_000,
                        "query_profiler_real_time_period_ns": 10_000_000,
                        "memory_profiler_step": 1_048_576,
                        "max_execution_time": 30,
                    },
                    query_id=profile_query_id,
                )
        except Exception:
            logger.exception("Query profiling failed for query_id %s", profile_query_id)
            raise exceptions.ValidationError("Query execution failed.")
        execution_time_ms = round((time.monotonic() - start_time) * 1000)

        return Response(
            {
                "profile_query_id": profile_query_id,
                "execution_time_ms": execution_time_ms,
            }
        )

    @action(detail=False, methods=["GET"], url_path="profile_results")
    def profile_results(self, request):
        if not request.user.is_staff:
            raise exceptions.PermissionDenied("Only staff users can profile queries.")

        profile_query_id = request.query_params.get("profile_query_id", "").strip()
        if not profile_query_id:
            raise exceptions.ValidationError("No profile_query_id provided.")

        try:
            trace_results = sync_execute(
                """
                SELECT
                    arrayStringConcat(arrayMap(x -> demangle(addressToSymbol(x)), trace), ';') AS stack,
                    count() AS samples
                FROM clusterAllReplicas(%(cluster)s, system, trace_log)
                WHERE query_id = %(query_id)s AND trace_type = 'CPU'
                GROUP BY trace
                HAVING stack != ''
                SETTINGS allow_introspection_functions=1, skip_unavailable_shards=1
                """,
                {"query_id": profile_query_id, "cluster": CLICKHOUSE_CLUSTER},
            )
        except Exception:
            raise exceptions.ValidationError(
                "Profiling data unavailable. The trace_log table may not be enabled on this ClickHouse instance."
            )

        if not trace_results:
            return Response({"status": "pending"}, status=202)

        folded_stacks = [f"{row[0]} {row[1]}" for row in trace_results]
        sample_count = sum(row[1] for row in trace_results)

        return Response({"status": "complete", "folded_stacks": folded_stacks, "sample_count": sample_count})
