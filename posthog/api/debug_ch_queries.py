import re
import json
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
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.cloud_utils import is_cloud
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import Team
from posthog.settings.base_variables import DEBUG
from posthog.settings.data_stores import CLICKHOUSE_CLUSTER

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

        tag_queries(product=Product.INTERNAL, feature=Feature.DEBUG_QUERY)

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

    def _serialize_precomputation_team(
        self, team: Team, enabled: bool, arr_by_org: dict[str, int] | None = None
    ) -> dict:
        org_id = str(team.organization.id) if team.organization else None
        return {
            "team_id": team.id,
            "team_name": team.name,
            "organization_id": org_id,
            "organization_name": team.organization.name if team.organization else None,
            "organization_arr": arr_by_org.get(org_id, None) if arr_by_org and org_id else None,
            "experiment_precomputation_enabled": enabled,
        }

    @action(detail=False, methods=["GET", "POST"], url_path="precomputation_teams")
    def precomputation_teams(self, request):
        if not request.user.is_staff:
            raise exceptions.PermissionDenied("Only staff users can manage precomputation teams.")

        tag_queries(product=Product.INTERNAL, feature=Feature.DEBUG_QUERY)

        if request.method == "POST":
            return self._update_precomputation(request)

        search = request.query_params.get("search", "").strip()

        if search:
            # Search by org name — return all teams in matching orgs
            teams = list(
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
            org_ids = {str(t.organization.id) for t in teams if t.organization}
            arr_by_org = self._fetch_org_arr(org_ids) if org_ids else {}
            return Response(
                [
                    self._serialize_precomputation_team(team, configs_by_team.get(team.id, False), arr_by_org)
                    for team in teams
                ]
            )

        # Default: only teams with precomputation enabled
        configs = list(
            TeamExperimentsConfig.objects.filter(experiment_precomputation_enabled=True)
            .select_related("team", "team__organization")
            .order_by("team__name")
        )
        org_ids = {str(c.team.organization.id) for c in configs if c.team.organization}
        arr_by_org = self._fetch_org_arr(org_ids) if org_ids else {}
        return Response([self._serialize_precomputation_team(config.team, True, arr_by_org) for config in configs])

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

        org_id = str(team.organization.id) if team.organization else None
        arr_by_org = self._fetch_org_arr({org_id}) if org_id else {}
        return Response(self._serialize_precomputation_team(team, enabled, arr_by_org))

    # Team ID for PostHog's own project, which has data warehouse billing tables
    _POSTHOG_INTERNAL_TEAM_ID = 2

    def _fetch_org_arr(self, org_ids: set[str]) -> dict[str, int]:
        """Fetch current confirmed ARR per organization from data warehouse billing tables.

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
                    round(sum(iwa.mrr) * 12) AS current_arr
                FROM prod_postgres_invoice_with_annual AS iwa
                JOIN prod_postgres_billing_customer AS cus ON iwa.customer_id = cus.id
                WHERE
                    cus.organization_id IN ({org_id_list})
                    AND iwa.type NOT LIKE '%upcoming%'
                    AND iwa.mrr > 0
                    AND toStartOfMonth(toTimeZone(iwa.period_end, 'UTC')) = toStartOfMonth(now() - INTERVAL 1 MONTH)
                GROUP BY cus.organization_id
                """,
                team=team,
                query_type="internal_org_mrr",
            )
            return {str(row[0]): round(float(row[1])) for row in response.results or []}
        except Exception:
            logger.warning("Failed to fetch org ARR from billing tables, skipping", exc_info=True)
            return {}

    @action(detail=False, methods=["GET"], url_path="slowest_queries")
    def slowest_queries(self, request):
        if not request.user.is_staff:
            raise exceptions.PermissionDenied("Only staff users can view slowest queries.")

        tag_queries(product=Product.INTERNAL, feature=Feature.DEBUG_QUERY)

        try:
            hours = int(request.query_params.get("hours", 1))
        except (TypeError, ValueError):
            raise exceptions.ValidationError("hours must be an integer.")
        hours = max(1, min(hours, 168))  # clamp to 1h–7d

        team_id_filter: Optional[int] = None
        if request.query_params.get("team_id"):
            try:
                team_id_filter = int(request.query_params["team_id"])
            except (TypeError, ValueError):
                raise exceptions.ValidationError("team_id must be an integer.")
            if team_id_filter <= 0:
                raise exceptions.ValidationError("team_id must be a positive integer.")

        experiment_id_filter: Optional[int] = None
        if request.query_params.get("experiment_id"):
            try:
                experiment_id_filter = int(request.query_params["experiment_id"])
            except (TypeError, ValueError):
                raise exceptions.ValidationError("experiment_id must be an integer.")
            if experiment_id_filter <= 0:
                raise exceptions.ValidationError("experiment_id must be a positive integer.")

        params: dict = {
            "cluster": CLICKHOUSE_CLUSTER,
            "hours": hours,
            "not_query": "%request:_api_debug_ch_queries_%",
        }
        extra_filters = ""
        if team_id_filter is not None:
            extra_filters += " AND JSONExtractInt(log_comment, 'team_id') = %(team_id)s"
            params["team_id"] = team_id_filter
        if experiment_id_filter is not None:
            extra_filters += " AND JSONExtractInt(log_comment, 'experiment_id') = %(experiment_id)s"
            params["experiment_id"] = experiment_id_filter

        # nosemgrep: clickhouse-fstring-param-audit - extra_filters is built from hardcoded SQL fragments; user values flow through params
        sql_query = f"""
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
                    {extra_filters}
                SETTINGS skip_unavailable_shards=1
            )
            GROUP BY query_id
            ORDER BY query_duration_ms DESC
            LIMIT 100
            """

        response = sync_execute(sql_query, params)

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

        # Batch-fetch current ARR per organization from billing tables
        org_ids = {t["organization_id"] for t in teams_by_id.values() if t.get("organization_id")}
        arr_by_org: dict[str, int] = {}
        if org_ids:
            arr_by_org = self._fetch_org_arr(org_ids)

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
                    "organization_arr": arr_by_org.get(teams_by_id.get(row[6], {}).get("organization_id", ""), None),
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
