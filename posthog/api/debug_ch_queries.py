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

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload, get_client_from_pool
from posthog.cloud_utils import is_cloud
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import Team
from posthog.settings.base_variables import DEBUG
from posthog.settings.data_stores import CLICKHOUSE_CLUSTER
from posthog.utils import generate_short_id

from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig

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

    _ALLOWED_FILTER_KEYS = frozenset({"insight_id", "experiment_id"})

    def _log_comment_filter(self, filter_key: str, filter_value: str) -> str:
        """Build a WHERE clause filtering on a log_comment JSON field."""
        if filter_key not in self._ALLOWED_FILTER_KEYS:
            raise ValueError(f"Invalid filter_key: {filter_key!r}")
        return f"JSONExtractRaw(log_comment, '{filter_key}') = %(filter_value)s"

    def hourly_stats(self, filter_key: str, filter_value: str):
        params = {
            "filter_value": filter_value,
            "start_time": (datetime.now() - timedelta(days=14)).timestamp(),
            "not_query": "%request:_api_debug_ch_queries_%",
            "cluster": CLICKHOUSE_CLUSTER,
        }

        # nosemgrep: clickhouse-fstring-param-audit - filter_clause from internal _log_comment_filter
        filter_clause = self._log_comment_filter(filter_key, filter_value)
        sql_query = f"""
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
                        {filter_clause} AND
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

    def stats(self, filter_key: str, filter_value: str):
        params = {
            "filter_value": filter_value,
            "start_time": (datetime.now(UTC) - timedelta(days=14)).timestamp(),
            "cluster": CLICKHOUSE_CLUSTER,
        }

        # nosemgrep: clickhouse-fstring-param-audit - filter_clause from internal _log_comment_filter
        filter_clause = self._log_comment_filter(filter_key, filter_value)
        sql_query = f"""
            SELECT
                count(*) AS total_queries,
                countIf(exception != '') AS total_exceptions,
                avg(query_duration_ms) AS average_query_duration_ms,
                max(query_duration_ms) AS max_query_duration_ms,
                (countIf(exception != '') / count(*)) * 100 AS exception_percentage
            FROM (
                SELECT
                    query_id, query, query_start_time, exception, query_duration_ms
                FROM clusterAllReplicas(%(cluster)s, system, query_log)
                WHERE
                    {filter_clause} AND
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

    def queries(self, request: Request, filter_key: Optional[str] = None, filter_value: Optional[str] = None):
        params: dict = {
            "not_query": "%request:_api_debug_ch_queries_%",
            "cluster": CLICKHOUSE_CLUSTER,
        }
        limit_clause = ""

        if filter_key and filter_value:
            # nosemgrep: clickhouse-fstring-param-audit - where_clause from internal _log_comment_filter
            where_clause = self._log_comment_filter(filter_key, filter_value)
            params["filter_value"] = filter_value
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
        experiment_id = request.query_params.get("experiment_id")

        filter_key = None
        filter_value = None
        if insight_id:
            filter_key, filter_value = "insight_id", insight_id
        elif experiment_id:
            filter_key, filter_value = "experiment_id", experiment_id

        queries = self.queries(request, filter_key, filter_value)
        response = {"queries": queries}
        if filter_key and filter_value:
            response["stats"] = self.stats(filter_key, filter_value)
            response["hourly_stats"] = self.hourly_stats(filter_key, filter_value)
        return Response(response)

    def _serialize_precomputation_team(self, team: Team, enabled: bool) -> dict:
        return {
            "team_id": team.id,
            "team_name": team.name,
            "organization_id": str(team.organization.id) if team.organization else None,
            "organization_name": team.organization.name if team.organization else None,
            "experiment_precomputation_enabled": enabled,
        }

    @action(detail=False, methods=["GET", "POST"], url_path="precomputation_teams")
    def precomputation_teams(self, request):
        if not request.user.is_staff:
            raise exceptions.PermissionDenied("Only staff users can manage precomputation teams.")

        if request.method == "POST":
            return self._update_precomputation(request)

        search = request.query_params.get("search", "").strip()

        if search:
            # Search by org name — return all teams in matching orgs
            teams = (
                Team.objects.filter(organization__name__icontains=search)
                .select_related("organization")
                .order_by("organization__name", "name")
            )
            # Batch-fetch precomputation configs for matched teams
            configs_by_team = dict(
                TeamExperimentsConfig.objects.filter(
                    team__in=teams,
                    experiment_precomputation_enabled=True,
                ).values_list("team_id", "experiment_precomputation_enabled")
            )
            return Response(
                [self._serialize_precomputation_team(team, configs_by_team.get(team.id, False)) for team in teams]
            )

        # Default: only teams with precomputation enabled
        configs = (
            TeamExperimentsConfig.objects.filter(experiment_precomputation_enabled=True)
            .select_related("team", "team__organization")
            .order_by("team__name")
        )
        return Response([self._serialize_precomputation_team(config.team, True) for config in configs])

    def _update_precomputation(self, request) -> Response:
        team_id = request.data.get("team_id")
        enabled = request.data.get("experiment_precomputation_enabled")

        if team_id is None or enabled is None:
            raise exceptions.ValidationError("team_id and experiment_precomputation_enabled are required.")

        try:
            team = Team.objects.select_related("organization").get(id=int(team_id))
        except (Team.DoesNotExist, TypeError, ValueError):
            raise exceptions.NotFound(f"Team {team_id} not found.")

        config = get_or_create_team_extension(team, TeamExperimentsConfig)
        config.experiment_precomputation_enabled = enabled
        config.save(update_fields=["experiment_precomputation_enabled"])

        return Response(self._serialize_precomputation_team(team, enabled))

    # Team ID for PostHog's own project, which has data warehouse billing tables
    _POSTHOG_INTERNAL_TEAM_ID = 2

    def _fetch_org_mrr(self, org_ids: set[str]) -> dict[str, int]:
        """Fetch current confirmed MRR per organization from data warehouse billing tables.

        Uses HogQL to access data warehouse tables via the PostHog internal team.
        Returns empty dict if unavailable (e.g. local dev or missing tables).
        """
        try:
            team = Team.objects.get(id=self._POSTHOG_INTERNAL_TEAM_ID)
        except Team.DoesNotExist:
            return {}

        org_id_list = ", ".join(f"'{org_id}'" for org_id in org_ids)

        try:
            # nosemgrep: hogql-fstring-param-audit - org_ids are UUIDs from our own DB
            response = execute_hogql_query(
                f"""
                SELECT
                    cus.organization_id,
                    round(sum(iwa.mrr)) AS current_mrr
                FROM prod_postgres_invoice_with_annual AS iwa
                JOIN prod_postgres_billing_customer AS cus ON iwa.customer_id = cus.id
                WHERE
                    cus.organization_id IN ({org_id_list})
                    AND iwa.type NOT LIKE '%upcoming%'
                    AND iwa.mrr > 0
                    AND toStartOfMonth(toTimeZone(iwa.period_end, 'UTC')) = toStartOfMonth(now())
                GROUP BY cus.organization_id
                """,
                team=team,
                query_type="internal_org_mrr",
            )
            return {str(row[0]): round(float(row[1])) for row in response.results or []}
        except Exception:
            logger.warning("Failed to fetch org MRR from billing tables, skipping", exc_info=True)
            return {}

    @action(detail=False, methods=["GET"], url_path="slowest_queries")
    def slowest_queries(self, request):
        if not request.user.is_staff:
            raise exceptions.PermissionDenied("Only staff users can view slowest queries.")

        try:
            hours = int(request.query_params.get("hours", 1))
        except (TypeError, ValueError):
            raise exceptions.ValidationError("hours must be an integer.")
        hours = max(1, min(hours, 168))  # clamp to 1h–7d

        response = sync_execute(
            """
            SELECT
                query_id,
                argMax(query, type) AS query,
                argMax(query_start_time, type) AS query_start_time,
                argMax(query_duration_ms, type) AS query_duration_ms,
                argMax(exception, type) AS exception,
                max(type) AS status,
                argMax(JSONExtractInt(log_comment, 'team_id'), type) AS team_id,
                argMax(JSONExtractString(log_comment, 'query_type'), type) AS query_type,
                argMax(JSONExtractString(log_comment, 'experiment_name'), type) AS experiment_name,
                argMax(JSONExtractString(log_comment, 'experiment_metric_name'), type) AS experiment_metric_name,
                argMax(JSONExtractString(log_comment, 'experiment_execution_path'), type) AS experiment_execution_path,
                argMax(JSONExtractString(log_comment, 'experiment_metric_type'), type) AS experiment_metric_type,
                argMax(JSONExtractInt(log_comment, 'experiment_id'), type) AS experiment_id
            FROM (
                SELECT
                    query_id, query, query_start_time, query_duration_ms, exception,
                    toInt8(type) AS type, log_comment
                FROM clusterAllReplicas(%(cluster)s, system, query_log)
                WHERE
                    event_time > now() - INTERVAL %(hours)s HOUR
                    AND JSONExtractString(log_comment, 'product') = 'experiments'
                    AND is_initial_query
                    AND query NOT LIKE %(not_query)s
                SETTINGS skip_unavailable_shards=1
            )
            GROUP BY query_id
            ORDER BY query_duration_ms DESC
            LIMIT 100
            """,
            {
                "cluster": CLICKHOUSE_CLUSTER,
                "hours": hours,
                "not_query": "%request:_api_debug_ch_queries_%",
            },
        )

        # Batch-fetch team and org names from Postgres
        team_ids = {row[6] for row in response if row[6]}
        teams_by_id: dict = {}
        if team_ids:
            for team in Team.objects.filter(id__in=team_ids).select_related("organization"):
                teams_by_id[team.id] = {
                    "team_name": team.name,
                    "organization_id": str(team.organization.id) if team.organization else None,
                    "organization_name": team.organization.name if team.organization else None,
                }

        # Batch-fetch current MRR per organization from billing tables
        org_ids = {t["organization_id"] for t in teams_by_id.values() if t.get("organization_id")}
        mrr_by_org: dict[str, int] = {}
        if org_ids:
            mrr_by_org = self._fetch_org_mrr(org_ids)

        return Response(
            [
                {
                    "query_id": row[0],
                    "query": row[1],
                    "timestamp": row[2],
                    "execution_time": row[3],
                    "exception": row[4],
                    "status": row[5],
                    "team_id": row[6],
                    "team_name": teams_by_id.get(row[6], {}).get("team_name"),
                    "organization_name": teams_by_id.get(row[6], {}).get("organization_name"),
                    "organization_mrr": mrr_by_org.get(teams_by_id.get(row[6], {}).get("organization_id", ""), None),
                    "query_type": row[7],
                    "experiment_name": row[8],
                    "experiment_metric_name": row[9],
                    "experiment_execution_path": row[10],
                    "experiment_metric_type": row[11],
                    "experiment_id": row[12] or None,
                }
                for row in response
            ]
        )

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
