import re
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from django.db.models import Count
from django.utils.timezone import now

from dateutil.relativedelta import relativedelta
from drf_spectacular.utils import extend_schema
from loginas.utils import is_impersonated_session
from rest_framework import exceptions, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.hogql.query import execute_hogql_query

from posthog.auth import PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.experiment_exposures_sql import (
    DISTRIBUTED_EXPERIMENT_EXPOSURES_TABLE,
    SHARDED_EXPERIMENT_EXPOSURES_TABLE,
)
from posthog.clickhouse.preaggregation.experiment_metric_events_sql import (
    DISTRIBUTED_EXPERIMENT_METRIC_EVENTS_TABLE,
    SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE,
)
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.cloud_utils import is_cloud
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import Team
from posthog.permissions import APIScopePermission
from posthog.settings.base_variables import DEBUG
from posthog.settings.data_stores import CLICKHOUSE_CLUSTER, CLICKHOUSE_DATABASE

from products.analytics_platform.backend.models import PreaggregationJob
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig

logger = logging.getLogger(__name__)


def _nest_subqueries(records: list[dict]) -> list[dict]:
    """Group the flat slowest-query rows into top-level reads, each carrying its precompute-build
    sub-queries under ``sub_queries``. Rows sharing an ``experiment_query_group_id`` form one group
    (rows without one are their own group, keyed by ``query_id``); the non-``precompute_build`` row is
    the parent. ``records`` must already be ordered for display (group total desc, parent first), which
    the SQL guarantees — dict insertion order is then preserved as the output order.
    """
    groups: dict[str, dict] = {}
    extra_parents: list[dict] = []
    for record in records:
        key = record["experiment_query_group_id"] or record["query_id"]
        bucket = groups.setdefault(key, {"parent": None, "children": []})
        if record["experiment_query_surface"] == "precompute_build":
            bucket["children"].append(record)
        elif bucket["parent"] is None:
            bucket["parent"] = record
        else:
            # The runner mints one group id per evaluation, so >1 top-level read per group isn't
            # expected. If it happens, keep the first as the group's parent and surface the rest
            # standalone rather than dropping them.
            logger.warning("slowest_queries: multiple top-level reads share group %s", key)
            extra_parents.append(record)

    results: list[dict] = []
    for bucket in groups.values():
        parent = bucket["parent"]
        if parent is None:
            # Sub-queries whose top-level read isn't in the window — show standalone so nothing is hidden.
            results.extend(bucket["children"])
            continue
        parent["sub_queries"] = bucket["children"]
        results.append(parent)
    results.extend(extra_parents)
    return results


def _cache_table_stats() -> list[dict]:
    """Physical footprint of the experiment preaggregation tables, from system.parts.

    Both tables are PARTITION BY toYYYYMMDD(expires_at) with TTL expires_at and
    ttl_only_drop_parts=1, so each partition id is the day the partition drops — the
    per-partition breakdown doubles as a TTL/growth timeline.
    """
    tables = {
        SHARDED_EXPERIMENT_EXPOSURES_TABLE(): DISTRIBUTED_EXPERIMENT_EXPOSURES_TABLE(),
        SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE(): DISTRIBUTED_EXPERIMENT_METRIC_EVENTS_TABLE(),
    }
    # cluster() reads one replica per shard. clusterAllReplicas would visit every replica and,
    # unlike query_log (deduped via is_initial_query), each replica of a shard reports the same
    # parts — rows/bytes would be multiplied by the replica count.
    response = sync_execute(
        """
        SELECT
            table,
            partition,
            sum(rows) AS rows,
            sum(bytes_on_disk) AS bytes_on_disk,
            count() AS parts
        FROM cluster(%(cluster)s, system, parts)
        WHERE
            database = %(database)s
            AND table IN %(tables)s
            AND active
        GROUP BY table, partition
        ORDER BY table, partition
        SETTINGS skip_unavailable_shards=1
        """,
        {
            "cluster": CLICKHOUSE_CLUSTER,
            "database": CLICKHOUSE_DATABASE,
            "tables": list(tables.keys()),
        },
    )

    stats: dict[str, dict[str, Any]] = {
        sharded: {
            "table": base,
            "total_rows": 0,
            "bytes_on_disk": 0,
            "active_parts": 0,
            "partition_count": 0,
            "oldest_partition": None,
            "newest_partition": None,
            "partitions": [],
        }
        for sharded, base in tables.items()
    }
    for table, partition, rows, bytes_on_disk, parts in response:
        entry = stats.get(table)
        if entry is None:
            continue
        entry["total_rows"] += rows
        entry["bytes_on_disk"] += bytes_on_disk
        entry["active_parts"] += parts
        entry["partition_count"] += 1
        entry["partitions"].append(
            {"partition": partition, "rows": rows, "bytes_on_disk": bytes_on_disk, "parts": parts}
        )
    for entry in stats.values():
        if entry["partitions"]:
            entry["oldest_partition"] = entry["partitions"][0]["partition"]
            entry["newest_partition"] = entry["partitions"][-1]["partition"]
    return list(stats.values())


@extend_schema(exclude=True)
class DebugCHQueries(viewsets.ViewSet):
    """
    List recent CH queries initiated by this user.
    """

    # `scope_object = "INTERNAL"` blocks a staff user's full-access (`*`) PAT via the
    # wildcard short-circuit in `APIScopePermission.has_permission`. The action below pins
    # `query_performance:read` — an OAuth-hidden, PAT-grantable scope (see
    # OAUTH_HIDDEN_SCOPE_OBJECTS) that automation carries; the browser uses session auth,
    # which bypasses scope checks. `is_staff` gates the action itself in every case.
    scope_object = "INTERNAL"
    permission_classes = [IsAuthenticated, APIScopePermission]
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication]
    required_scopes: Optional[list[str]] = None

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

    @action(detail=False, methods=["GET"], url_path="slowest_queries", required_scopes=["query_performance:read"])
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

        metric_type_filter = request.query_params.get("metric_type") or None
        if metric_type_filter is not None and metric_type_filter not in {"mean", "funnel", "ratio", "retention"}:
            raise exceptions.ValidationError("metric_type must be one of: mean, funnel, ratio, retention.")

        funnel_order_type_filter = request.query_params.get("funnel_order_type") or None
        if funnel_order_type_filter is not None:
            if funnel_order_type_filter not in {"ordered", "unordered", "strict"}:
                raise exceptions.ValidationError("funnel_order_type must be one of: ordered, unordered, strict.")
            if metric_type_filter != "funnel":
                raise exceptions.ValidationError("funnel_order_type can only be used with metric_type=funnel.")

        exception_code_filter: Optional[int] = None
        if request.query_params.get("exception_code"):
            try:
                exception_code_filter = int(request.query_params["exception_code"])
            except (TypeError, ValueError):
                raise exceptions.ValidationError("exception_code must be an integer.")
            if exception_code_filter <= 0:
                raise exceptions.ValidationError("exception_code must be a positive integer.")

        params: dict = {
            "hours": hours,
            "not_query": "%request:_api_debug_ch_queries_%",
        }
        extra_filters = ""
        if team_id_filter is not None:
            extra_filters += " AND team_id = %(team_id)s"
            params["team_id"] = team_id_filter
        if experiment_id_filter is not None:
            extra_filters += " AND lc_experiment_id = %(experiment_id)s"
            params["experiment_id"] = experiment_id_filter
        # metric_type and funnel_order_type are tagged before the precompute builds run, so the build
        # sub-queries carry them too and stay grouped with their parent read under these filters.
        if metric_type_filter is not None:
            extra_filters += " AND toString(log_comment.experiment_metric_type) = %(metric_type)s"
            params["metric_type"] = metric_type_filter
        if funnel_order_type_filter is not None:
            extra_filters += " AND toString(log_comment.experiment_funnel_order_type) = %(funnel_order_type)s"
            params["funnel_order_type"] = funnel_order_type_filter

        # Filter at the group level (a group's terminal exception_code, resolved per query_id in per_query):
        # keep groups where any query — read or precompute build — hit this code, so nesting stays intact.
        having_exception_code = ""
        if exception_code_filter is not None:
            having_exception_code = "HAVING countIf(exception_code = %(exception_code)s) > 0"
            params["exception_code"] = exception_code_filter

        # Each row is one ClickHouse query. A top-level read (surface != 'precompute_build') and the
        # precompute-build INSERTs it triggered share an experiment_query_group_id (set by the runner).
        # We rank groups by total duration (build + read — the user waited for both, synchronously) and
        # return every row of the top 100 groups; Python then nests the builds under their parent read.
        # Rows with no group id (legacy / non-runner queries) fall back to a group of one via `grp`.
        # Reads query_log_archive (not system.query_log, which retains only hours): log_comment is a
        # typed JSON column there, so tags are dot-accessed; ifNull(toString(...), '') preserves the
        # ''-when-missing semantics JSONExtractString gave us on the raw column.
        # nosemgrep: clickhouse-fstring-param-audit - extra_filters is built from hardcoded SQL fragments; user values flow through params
        sql_query = f"""
            WITH per_query AS (
                SELECT
                    query_id,
                    argMax(query, type) AS query,
                    argMax(query_start_time, type) AS query_start_time,
                    argMax(query_duration_ms, type) AS query_duration_ms,
                    argMax(exception, type) AS exception,
                    argMax(read_bytes, type) AS read_bytes,
                    argMax(read_rows, type) AS read_rows,
                    argMax(exception_code, type) AS exception_code,
                    argMax(memory_usage, type) AS memory_usage,
                    max(type) AS status,
                    argMax(team_id, type) AS team_id,
                    argMax(lc_query_type, type) AS query_type,
                    argMax(ifNull(toString(log_comment.experiment_name), ''), type) AS experiment_name,
                    argMax(ifNull(toString(log_comment.experiment_metric_name), ''), type) AS experiment_metric_name,
                    argMax(ifNull(toString(log_comment.experiment_execution_path), ''), type) AS experiment_execution_path,
                    argMax(ifNull(toString(log_comment.experiment_metric_type), ''), type) AS experiment_metric_type,
                    argMax(ifNull(toString(log_comment.experiment_funnel_order_type), ''), type) AS experiment_funnel_order_type,
                    argMax(lc_experiment_id, type) AS experiment_id,
                    argMax(ifNull(toString(log_comment.experiment_exposures_path), ''), type) AS experiment_exposures_path,
                    argMax(ifNull(toString(log_comment.experiment_metric_events_path), ''), type) AS experiment_metric_events_path,
                    argMax(ifNull(toString(log_comment.experiment_query_surface), ''), type) AS experiment_query_surface,
                    argMax(ifNull(toString(log_comment.experiment_precompute_table), ''), type) AS experiment_precompute_table,
                    argMax(ifNull(toString(log_comment.experiment_query_group_id), ''), type) AS experiment_query_group_id,
                    argMax(ifNull(toString(log_comment.experiment_precompute_skip_reason), ''), type) AS experiment_precompute_skip_reason,
                    argMax(ifNull(toString(log_comment.experiment_scan_date_from), ''), type) AS experiment_scan_date_from,
                    argMax(ifNull(toString(log_comment.experiment_scan_date_to), ''), type) AS experiment_scan_date_to,
                    argMax(ifNull(toString(log_comment.precompute_window_start), ''), type) AS precompute_window_start,
                    argMax(ifNull(toString(log_comment.precompute_window_end), ''), type) AS precompute_window_end
                FROM (
                    SELECT
                        query_id, query, query_start_time, query_duration_ms, exception,
                        read_bytes, read_rows, exception_code, memory_usage,
                        toInt8(type) AS type, log_comment, team_id, lc_query_type, lc_experiment_id
                    FROM query_log_archive
                    WHERE
                        event_date >= toDate(now() - INTERVAL %(hours)s HOUR)
                        AND event_time > now() - INTERVAL %(hours)s HOUR
                        AND lc_product = 'experiments'
                        AND is_initial_query
                        AND query NOT LIKE %(not_query)s
                        {extra_filters}
                )
                GROUP BY query_id
            ),
            grouped AS (
                SELECT *, coalesce(nullIf(experiment_query_group_id, ''), query_id) AS grp FROM per_query
            ),
            ranked AS (
                SELECT grp, sum(query_duration_ms) AS total_duration_ms
                FROM grouped
                GROUP BY grp
                {having_exception_code}
                ORDER BY total_duration_ms DESC
                LIMIT 100
            )
            SELECT
                g.query_id, g.query, g.query_start_time, g.query_duration_ms, g.exception, g.status,
                g.team_id, g.query_type, g.experiment_name, g.experiment_metric_name, g.experiment_execution_path,
                g.experiment_metric_type, g.experiment_funnel_order_type, g.experiment_id, g.experiment_exposures_path,
                g.experiment_metric_events_path, g.experiment_query_surface, g.experiment_precompute_table,
                g.experiment_query_group_id, r.total_duration_ms,
                g.read_bytes, g.read_rows, g.exception_code, g.memory_usage,
                g.experiment_precompute_skip_reason,
                g.experiment_scan_date_from, g.experiment_scan_date_to,
                g.precompute_window_start, g.precompute_window_end
            FROM grouped AS g
            INNER JOIN ranked AS r ON g.grp = r.grp
            ORDER BY
                r.total_duration_ms DESC,
                g.grp,
                g.experiment_query_surface = 'precompute_build' ASC,
                g.query_duration_ms DESC
            SETTINGS skip_unavailable_shards=1
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

        # Row indices follow the final SELECT projection above.
        def _record(row) -> dict:
            team = teams_by_id.get(row[6], {})
            return {
                "query_id": row[0],
                "query": row[1],
                "timestamp": row[2],
                "execution_time": row[3],
                "exception": row[4],
                "status": row[5],
                "team_id": row[6],
                "team_name": team.get("team_name"),
                "organization_name": team.get("organization_name"),
                "organization_arr": arr_by_org.get(team.get("organization_id", ""), None),
                "query_type": row[7],
                "experiment_name": row[8],
                "experiment_metric_name": row[9],
                "experiment_execution_path": row[10],
                "experiment_metric_type": row[11],
                "experiment_funnel_order_type": row[12] or None,
                "experiment_id": row[13] or None,
                "experiment_exposures_path": row[14],
                "experiment_metric_events_path": row[15],
                "experiment_query_surface": row[16],
                "experiment_precompute_table": row[17],
                "experiment_query_group_id": row[18],
                "total_duration_ms": row[19],
                "read_bytes": row[20],
                "read_rows": row[21],
                "exception_code": row[22],
                "memory_usage": row[23],
                "experiment_precompute_skip_reason": row[24],
                "experiment_scan_date_from": row[25],
                "experiment_scan_date_to": row[26],
                "precompute_window_start": row[27],
                "precompute_window_end": row[28],
                "sub_queries": [],
            }

        return Response(_nest_subqueries([_record(row) for row in response]))

    # Skip reasons the runner tags on reads that never attempted precompute. An empty reason on a
    # direct-scan read means precompute WAS attempted but the data wasn't ready (build failed/slow) —
    # that read paid for the build AND the full events scan, so it's the bucket to watch.
    _PRECOMPUTE_SKIP_REASONS = ("team_disabled", "min_runtime", "override_direct", "data_warehouse")

    @action(detail=False, methods=["GET"], url_path="precompute_overview", required_scopes=["query_performance:read"])
    def precompute_overview(self, request):
        if not request.user.is_staff:
            raise exceptions.PermissionDenied("Only staff users can view the precompute overview.")

        tag_queries(product=Product.INTERNAL, feature=Feature.DEBUG_QUERY)

        try:
            hours = int(request.query_params.get("hours", 24))
        except (TypeError, ValueError):
            raise exceptions.ValidationError("hours must be an integer.")
        hours = max(1, min(hours, 168))  # clamp to 1h–7d

        params: dict = {
            "hours": hours,
            "not_query": "%request:_api_debug_ch_queries_%",
        }

        skip_reason_counts = ",\n".join(
            f"countIf(skip_reason = '{reason}') AS skip_{reason}" for reason in self._PRECOMPUTE_SKIP_REASONS
        )
        # One terminal query_log row per query (toInt8(type) > 1 excludes QueryStart), so plain
        # counts are per-query without the GROUP BY query_id dedup the slowest_queries endpoint needs.
        # Duration/bytes stats only cover successful reads — failed ones have truncated durations.
        # Reads query_log_archive (not system.query_log, which retains only hours): log_comment is a
        # typed JSON column there, so tags are dot-accessed; ifNull(toString(...), '') preserves the
        # ''-when-missing semantics JSONExtractString gave us on the raw column.
        # nosemgrep: clickhouse-fstring-param-audit - skip_reason_counts is built from a hardcoded tuple
        reads_sql = f"""
            SELECT
                coalesce(
                    nullIf(toString(log_comment.experiment_exposures_path), ''),
                    ifNull(toString(log_comment.experiment_execution_path), '')
                ) AS exposures_path,
                count() AS reads,
                countIf(exception_code != 0) AS failed_reads,
                {skip_reason_counts},
                countIf(skip_reason = '') AS attempted,
                countIf(metric_events_path = 'precomputed') AS me_precomputed,
                countIf(metric_events_path = 'direct_scan') AS me_direct_scan,
                countIf(metric_events_path = 'not_applicable') AS me_not_applicable,
                avgIf(query_duration_ms, exception_code = 0) AS avg_duration_ms,
                quantileIf(0.5)(query_duration_ms, exception_code = 0) AS p50_duration_ms,
                quantileIf(0.9)(query_duration_ms, exception_code = 0) AS p90_duration_ms,
                avgIf(read_bytes, exception_code = 0) AS avg_read_bytes,
                sum(read_bytes) AS total_read_bytes
            FROM (
                SELECT
                    query_duration_ms, exception_code, read_bytes, log_comment,
                    ifNull(toString(log_comment.experiment_precompute_skip_reason), '') AS skip_reason,
                    ifNull(toString(log_comment.experiment_metric_events_path), '') AS metric_events_path
                FROM query_log_archive
                WHERE
                    event_date >= toDate(now() - INTERVAL %(hours)s HOUR)
                    AND event_time > now() - INTERVAL %(hours)s HOUR
                    AND lc_product = 'experiments'
                    AND toString(log_comment.experiment_query_surface) = 'metric'
                    AND is_initial_query
                    AND toInt8(type) > 1
                    AND query NOT LIKE %(not_query)s
            )
            GROUP BY exposures_path
            SETTINGS skip_unavailable_shards=1
            """
        reads_response = sync_execute(reads_sql, params)

        empty_path = {
            "reads": 0,
            "failed_reads": 0,
            "attempted": 0,
            "avg_duration_ms": None,
            "p50_duration_ms": None,
            "p90_duration_ms": None,
            "avg_read_bytes": None,
            "total_read_bytes": 0,
        }
        # Must match the projection order of reads_sql.
        reads_columns = (
            "exposures_path",
            "reads",
            "failed_reads",
            *(f"skip_{reason}" for reason in self._PRECOMPUTE_SKIP_REASONS),
            "attempted",
            "me_precomputed",
            "me_direct_scan",
            "me_not_applicable",
            "avg_duration_ms",
            "p50_duration_ms",
            "p90_duration_ms",
            "avg_read_bytes",
            "total_read_bytes",
        )

        def _empty_path_entry() -> dict:
            return {**empty_path, "skip_reasons": dict.fromkeys(self._PRECOMPUTE_SKIP_REASONS, 0)}

        reads_by_path: dict[str, dict] = {
            "precomputed": _empty_path_entry(),
            "direct_scan": _empty_path_entry(),
        }
        metric_events = {"precomputed": 0, "direct_scan": 0, "not_applicable": 0}
        for raw_row in reads_response:
            row = dict(zip(reads_columns, raw_row))
            path = row["exposures_path"] or "direct_scan"
            entry = reads_by_path.setdefault(path, _empty_path_entry())
            entry["reads"] += row["reads"]
            entry["failed_reads"] += row["failed_reads"]
            entry["attempted"] += row["attempted"]
            entry["total_read_bytes"] += row["total_read_bytes"]
            if row["reads"] > 0:
                for stat in ("avg_duration_ms", "p50_duration_ms", "p90_duration_ms", "avg_read_bytes"):
                    entry[stat] = row[stat]
            for reason in self._PRECOMPUTE_SKIP_REASONS:
                entry["skip_reasons"][reason] += row[f"skip_{reason}"]
            metric_events["precomputed"] += row["me_precomputed"]
            metric_events["direct_scan"] += row["me_direct_scan"]
            metric_events["not_applicable"] += row["me_not_applicable"]

        builds_sql = """
            SELECT
                ifNull(toString(log_comment.experiment_precompute_table), '') AS build_table,
                exception_code,
                count() AS builds,
                sum(query_duration_ms) AS total_duration_ms,
                sum(read_bytes) AS total_read_bytes
            FROM query_log_archive
            WHERE
                event_date >= toDate(now() - INTERVAL %(hours)s HOUR)
                AND event_time > now() - INTERVAL %(hours)s HOUR
                AND lc_product = 'experiments'
                AND toString(log_comment.experiment_query_surface) = 'precompute_build'
                AND is_initial_query
                AND toInt8(type) > 1
                AND query NOT LIKE %(not_query)s
            GROUP BY build_table, exception_code
            SETTINGS skip_unavailable_shards=1
            """
        builds_response = sync_execute(builds_sql, params)

        builds: dict[str, Any] = {
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "total_duration_ms": 0,
            "total_read_bytes": 0,
            "by_table": {},
            "failures_by_code": {},
        }
        for build_table, exception_code, count, total_duration_ms, total_read_bytes in builds_response:
            table_key = build_table or "unknown"
            table_entry = builds["by_table"].setdefault(table_key, {"succeeded": 0, "failed": 0})
            builds["total"] += count
            builds["total_duration_ms"] += total_duration_ms
            builds["total_read_bytes"] += total_read_bytes
            if exception_code == 0:
                builds["succeeded"] += count
                table_entry["succeeded"] += count
            else:
                builds["failed"] += count
                table_entry["failed"] += count
                code_key = str(exception_code)
                builds["failures_by_code"][code_key] = builds["failures_by_code"].get(code_key, 0) + count

        window_start = now() - timedelta(hours=hours)
        job_status_counts = dict(
            PreaggregationJob.objects.filter(created_at__gte=window_start).values_list("status").annotate(n=Count("id"))
        )
        jobs = {
            "ready": job_status_counts.get(PreaggregationJob.Status.READY, 0),
            "failed": job_status_counts.get(PreaggregationJob.Status.FAILED, 0),
            "pending": job_status_counts.get(PreaggregationJob.Status.PENDING, 0),
            # Marked FAILED by a waiter because the owning executor stopped heartbeating — crashes,
            # OOM-killed pods. Invisible in query_log (the INSERT never finished), so PG is the only source.
            "stale_failed": PreaggregationJob.objects.filter(
                created_at__gte=window_start,
                status=PreaggregationJob.Status.FAILED,
                error__startswith="Job was stale",
            ).count(),
            # PENDING far past any plausible INSERT runtime: nothing will ever mark these, and they
            # block the range they cover (waiters keep waiting on them until staleness detection fires).
            "stuck_pending": PreaggregationJob.objects.filter(
                status=PreaggregationJob.Status.PENDING,
                created_at__lt=now() - timedelta(minutes=15),
            ).count(),
        }

        total_reads = sum(entry["reads"] for entry in reads_by_path.values())
        total_failed_reads = sum(entry["failed_reads"] for entry in reads_by_path.values())
        return Response(
            {
                "hours": hours,
                "reads": {
                    "total": total_reads,
                    "failed": total_failed_reads,
                    "by_exposures_path": reads_by_path,
                    "metric_events": metric_events,
                },
                "builds": builds,
                "jobs": jobs,
            }
        )

    @action(detail=False, methods=["GET"], url_path="cache_health", required_scopes=["query_performance:read"])
    def cache_health(self, request):
        if not request.user.is_staff:
            raise exceptions.PermissionDenied("Only staff users can view cache health.")

        tag_queries(product=Product.INTERNAL, feature=Feature.DEBUG_QUERY)

        return Response({"tables": _cache_table_stats()})
