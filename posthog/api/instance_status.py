from typing import Any, Dict, List, Union

from django.conf import settings
from django.db import connection
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.async_migrations.status import async_migrations_ok
from posthog.gitsha import GIT_SHA
from posthog.internal_metrics.team import get_internal_metrics_dashboards
from posthog.permissions import OrganizationAdminAnyPermissions, SingleTenancyOrAdmin
from posthog.storage import object_storage
from posthog.utils import (
    dict_from_cursor_fetchall,
    get_helm_info_env,
    get_plugin_server_job_queues,
    get_plugin_server_version,
    get_redis_info,
    get_redis_queue_depth,
    is_plugin_server_alive,
    is_postgres_alive,
    is_redis_alive,
)
from posthog.version import VERSION


class InstanceStatusViewSet(viewsets.ViewSet):
    """
    Show info about instance for this user
    """

    permission_classes = [IsAuthenticated, SingleTenancyOrAdmin]

    def list(self, request: Request) -> Response:
        redis_alive = is_redis_alive()
        postgres_alive = is_postgres_alive()

        metrics: List[Dict[str, Union[str, bool, int, float, Dict[str, Any]]]] = []

        metrics.append({"key": "posthog_version", "metric": "PostHog version", "value": VERSION})

        metrics.append({"key": "posthog_git_sha", "metric": "PostHog Git SHA", "value": GIT_SHA})

        helm_info = get_helm_info_env()
        if len(helm_info) > 0:
            metrics.append(
                {
                    "key": "helm",
                    "metric": "Helm Info",
                    "value": "",
                    "subrows": {"columns": ["key", "value"], "rows": list(helm_info.items())},
                }
            )

        metrics.append(
            {"key": "plugin_sever_alive", "metric": "Plugin server alive", "value": is_plugin_server_alive()}
        )
        metrics.append(
            {
                "key": "plugin_sever_version",
                "metric": "Plugin server version",
                "value": get_plugin_server_version() or "unknown",
            }
        )

        plugin_server_queues = get_plugin_server_job_queues()
        metrics.append(
            {
                "key": "plugin_sever_job_queues",
                "metric": "Job queues enabled in plugin server",
                "value": ", ".join([q.capitalize() for q in plugin_server_queues])
                if plugin_server_queues
                else "unknown",
            }
        )

        metrics.append({"key": "db_alive", "metric": "Postgres database alive", "value": postgres_alive})
        if postgres_alive:
            postgres_version = connection.cursor().connection.server_version
            metrics.append(
                {
                    "key": "pg_version",
                    "metric": "Postgres version",
                    "value": f"{postgres_version // 10000}.{(postgres_version // 100) % 100}.{postgres_version % 100}",
                }
            )
            metrics.append(
                {"key": "async_migrations_ok", "metric": "Async migrations up-to-date", "value": async_migrations_ok()},
            )

        from posthog.clickhouse.system_status import system_status

        metrics.extend(list(system_status()))

        metrics.append({"key": "redis_alive", "metric": "Redis alive", "value": redis_alive})
        if redis_alive:
            import redis

            try:
                redis_info = get_redis_info()
                redis_queue_depth = get_redis_queue_depth()
                metrics.append({"metric": "Redis version", "value": f"{redis_info.get('redis_version')}"})
                metrics.append({"metric": "Redis current queue depth", "value": f"{redis_queue_depth}"})
                metrics.append(
                    {"metric": "Redis connected client count", "value": f"{redis_info.get('connected_clients')}"}
                )
                metrics.append({"metric": "Redis memory used", "value": f"{redis_info.get('used_memory_human', '?')}B"})
                metrics.append(
                    {"metric": "Redis memory peak", "value": f"{redis_info.get('used_memory_peak_human', '?')}B"}
                )
                metrics.append(
                    {
                        "metric": "Redis total memory available",
                        "value": f"{redis_info.get('total_system_memory_human', '?')}B",
                    }
                )
                metrics.append(
                    {"metric": "Redis 'maxmemory' setting", "value": f"{redis_info.get('maxmemory_human', '?')}B"}
                )
                metrics.append(
                    {
                        "metric": "Redis 'maxmemory-policy' setting",
                        "value": f"{redis_info.get('maxmemory_policy', '?')}",
                    }
                )
            except redis.exceptions.ConnectionError as e:
                metrics.append(
                    {"metric": "Redis metrics", "value": f"Redis connected but then failed to return metrics: {e}"}
                )

        metrics.append(
            {"key": "object_storage", "metric": "Object Storage enabled", "value": settings.OBJECT_STORAGE_ENABLED}
        )
        if settings.OBJECT_STORAGE_ENABLED:
            metrics.append(
                {"key": "object_storage", "metric": "Object Storage healthy", "value": object_storage.health_check()}
            )

        return Response({"results": {"overview": metrics, "internal_metrics": get_internal_metrics_dashboards()}})

    # Used to capture internal metrics shown on dashboards
    @action(methods=["POST"], detail=False, permission_classes=[AllowAny])
    def capture(self, request: Request) -> Response:
        from posthog.internal_metrics import incr, timing

        method: Any = timing if request.data["method"] == "timing" else incr
        method(request.data["metric"], request.data["value"], request.data.get("tags", None))
        return Response({"status": 1})

    @action(methods=["GET"], detail=False)
    def queries(self, request: Request) -> Response:
        queries = {"postgres_running": self.get_postgres_running_queries()}

        from posthog.clickhouse.system_status import get_clickhouse_running_queries, get_clickhouse_slow_log

        queries["clickhouse_running"] = get_clickhouse_running_queries()
        queries["clickhouse_slow_log"] = get_clickhouse_slow_log()

        return Response({"results": queries})

    @action(
        methods=["POST"],
        detail=False,
        permission_classes=[IsAuthenticated, SingleTenancyOrAdmin, OrganizationAdminAnyPermissions],
    )
    def analyze_ch_query(self, request: Request) -> Response:
        response = {}

        from posthog.clickhouse.system_status import analyze_query

        response["results"] = analyze_query(request.data["query"])

        return Response(response)

    def get_postgres_running_queries(self):
        from django.db import connection

        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT now() - query_start as duration, state, query, query_start
            FROM pg_stat_activity
            WHERE query NOT LIKE '%pg_stat_activity%'
              AND query != ''
              AND now() - query_start > INTERVAL '3 seconds'
            ORDER BY state, duration DESC
        """
        )

        return dict_from_cursor_fetchall(cursor)
