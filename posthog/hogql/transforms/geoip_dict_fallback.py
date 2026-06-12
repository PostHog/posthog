"""Temporary ClickHouse pass: recover blanked `$geoip_city_name` / `$geoip_postal_code` event properties at query time.

A bad MaxMind GeoLite2-City release (June 2026 incident: https://posthog.slack.com/archives/C0B9DDSCTF1) blanked city and postal data on enriched events, and the
ALTER UPDATE backfill over the affected partitions is slow. Until it catches up, this pass patches reads of the two
affected properties: when the stored value is blank but geoip enrichment did run (`$geoip_country_code` is set) the
value is recovered from the event's `$ip` via the `city_postal_ip_trie` ClickHouse dictionary, which was built from a
healthy GeoLite2 build. The country-code guard keeps never-enriched rows (geoip disabled, pre-geoip events) blank, so
only rows the incident could have affected change.

Gated on the `HOGQL_GEOIP_DICT_FALLBACK_TEAMS` env var: a comma-separated list of team ids, or "*" for all teams;
empty (the default) disables it everywhere. Deliberately not a query modifier so it is operator-controlled only and
leaves nothing persisted in `team.modifiers` or saved queries to scrub at removal time. The gate also verifies at
runtime that the dictionary exists, healthy, on every node of the cluster (cached in-process like materialized-column
discovery), so the transform stands down instead of printing failing SQL wherever the manually provisioned dictionary
is absent or broken. The transform never applies to `within_non_hogql_query` fragments: those splice into DELETE
mutations (data deletion requests) and legacy filters, where the matched row set must not depend on env/probe state.

Operational runbook (the env var must be set identically on every deployment that compiles HogQL — web, celery,
query service, temporal — per region):
- Enable: provision the dictionary ON CLUSTER and verify `system.dictionaries` on every node FIRST, then set the env
  var, staged team lists before "*" ("*" changes every team's query cache key at once, a fleet-wide recompute).
- Remove: empty the env var on all deployments and confirm rollout, then delete this file with its callsite in
  `printer/utils.py`, the context field in `context.py`, the cache-payload entry in `query_runner.py`, the env
  setting, and the `_lookupGeoip*` functions — and only then drop the dictionary and its source table (dropping the
  dictionary first leaves up to 15 minutes of cached "healthy" probes printing SQL that hard-fails).

Runs between logical property lowering and ClickHouse property resolution: each affected `PropertyAccess` becomes a
conditional over three property reads (the property itself, `$geoip_country_code`, `$ip`), and the resolution pass
then routes each read through its materialized column where one exists — so on cloud the whole fallback runs off
`mat_*` columns plus an in-RAM dictionary lookup, without touching the `properties` blob.

Known limitation: property-level access control applies to the fallback's source reads like to any other read, so for
a user with `$ip` (or `$geoip_country_code`) restricted, those reads scrub to NULL, the dictionary lookup misses, and
the blanked values stay blank — even though the derived city/postal is itself readable to them. Accepted deliberately:
making that case recover would mean exempting the internal reads from the restriction boundary, which is not worth it
for a temporary fix. Nothing leaks and nothing errors; recovery just quietly misses for those users.

Scope: only event-property reads are covered. The incident also blanked person geo properties (the enrichment `$set`s
the same `$geoip_*` fields onto persons) and the values baked into derived stores (sessions, web analytics
preaggregated tables); those need their own fixes and are deliberately out of scope here — there is no per-person
`$ip` to recover from at query time.
"""

from datetime import timedelta
from typing import cast

from django.conf import settings

import structlog

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField
from posthog.hogql.printer.base import get_geoip_city_postal_dict
from posthog.hogql.restricted_properties import restricted_property_keys_for_table_type
from posthog.hogql.visitor import CloningVisitor, clone_expr

from posthog.cache_utils import cache_for
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.settings import CLICKHOUSE_CLUSTER

logger = structlog.get_logger(__name__)

FALLBACK_PROPERTY_TO_FUNCTION = {
    "$geoip_city_name": "_lookupGeoipCityName",
    "$geoip_postal_code": "_lookupGeoipPostalCode",
}


@cache_for(timedelta(minutes=15), background_refresh=True)
def _geoip_dict_exists() -> bool:
    """Whether the `city_postal_ip_trie` dictionary exists, healthy, on every node of the cluster.

    The dictionary is manually provisioned (no migration), so this mirrors the runtime materialized-column discovery:
    checked against `system.dictionaries` and cached in-process. The emitted `dictGet` executes on every shard and
    replica that serves events queries, so the probe fans out via `clusterAllReplicas` and requires the dictionary
    DDL on every node with none in a failed state — partial provisioning or a broken source disables the fallback
    everywhere rather than hard-failing queries on the nodes that lack it. A failed probe counts as absent: a
    ClickHouse blip degrades the fallback, never the query.
    """
    database, _, name = get_geoip_city_postal_dict().partition(".")
    try:
        # The cluster name comes from operator settings, not user input, mirroring ON_CLUSTER_CLAUSE.
        rows = sync_execute(
            f"""
            SELECT
                (SELECT count() FROM clusterAllReplicas('{CLICKHOUSE_CLUSTER}', system.one)) AS total_nodes,
                count() AS nodes_with_dictionary,
                countIf(status IN ('FAILED', 'FAILED_AND_RELOADING')) AS failed_nodes
            FROM clusterAllReplicas('{CLICKHOUSE_CLUSTER}', system.dictionaries)
            WHERE database = %(database)s AND name = %(name)s
            """,
            {"database": database, "name": name},
            settings={"max_execution_time": 5},
            ch_user=ClickHouseUser.HOGQL,
        )
        total_nodes, nodes_with_dictionary, failed_nodes = rows[0]
        healthy = total_nodes > 0 and nodes_with_dictionary == total_nodes and failed_nodes == 0
        if not healthy:
            logger.warning(
                "geoip_dict_fallback_dictionary_unhealthy",
                total_nodes=total_nodes,
                nodes_with_dictionary=nodes_with_dictionary,
                failed_nodes=failed_nodes,
            )
        return healthy
    except Exception:
        # The fallback silently standing down is itself an incident-mitigation failure, so make it visible.
        logger.warning("geoip_dict_fallback_dictionary_probe_failed", exc_info=True)
        return False


def geoip_dict_fallback_team_in_env(team_id: int | None) -> bool:
    """Whether the env var lists this team ("*" matches every team). Pure config, no ClickHouse dependency.

    This is the half used for query cache keys: keys must depend only on operator-controlled config, never on the
    runtime dictionary probe, or a transient probe failure would flip every enabled team's cache keys at once and
    recompute the fleet against an already-degraded cluster.
    """
    raw = settings.HOGQL_GEOIP_DICT_FALLBACK_TEAMS.strip()
    if not raw or team_id is None:
        return False
    return raw == "*" or str(team_id) in {part.strip() for part in raw.split(",")}


def geoip_dict_fallback_enabled_for_team(team_id: int | None) -> bool:
    """Whether the env var enables the fallback for this team and the dictionary is healthy cluster-wide."""
    return geoip_dict_fallback_team_in_env(team_id) and _geoip_dict_exists()


class GeoipDictFallback(CloningVisitor):
    """Wraps events `properties.$geoip_city_name` / `properties.$geoip_postal_code` reads with the dictionary fallback."""

    def __init__(self, context: HogQLContext) -> None:
        super().__init__(clear_types=False)
        self.context = context

    def visit_property_access(self, node: ast.PropertyAccess) -> ast.Expr:
        node = super().visit_property_access(node)
        if len(node.keys) != 1:
            return node
        property_name = str(node.keys[0])
        function_name = FALLBACK_PROPERTY_TO_FUNCTION.get(property_name)
        if function_name is None:
            return node
        table_type = self._events_properties_table_type(node)
        if table_type is None:
            return node
        # Property-level access control resolves restricted reads to NULL later in the pipeline; wrapping such a read
        # would reconstruct the restricted value from `$ip` on every enriched row, so the fallback must stand down
        # when the target property is restricted. Only the event scope counts: this is an events-table read, so a
        # person/group-scoped restriction on the same name doesn't affect it. Restricted sources need no guard and
        # don't disable it: the restriction layer scrubs those reads to NULL, so recovery quietly misses without
        # exposing them. Known accepted limitation: a user with `$ip` restricted keeps blank values even though the
        # derived property is readable — punching the restriction boundary for the internal reads was not worth it
        # for a temporary fix.
        if property_name in restricted_property_keys_for_table_type(table_type, self.context):
            return node
        return self._with_fallback(node, function_name)

    def _events_properties_table_type(self, node: ast.PropertyAccess) -> ast.TableType | None:
        """The events table type when the read targets the events `properties` blob, else None.

        Person/group properties keep their stored values — including under persons-on-events, where they live on the
        events table behind a virtual sub-table whose blob field is also named `properties` but resolves to the
        `person_properties` / `group{N}_properties` column. Checking the resolved column name catches those. Note the
        incident DID blank person geo properties too (the enrichment `$set`s the same fields onto persons), but
        recovering them is a separate, harder fix that is deliberately out of scope here: this expression recovers
        from the event-time `$ip`, which has no per-person equivalent to read.
        """
        expr_type = node.expr.type
        if not isinstance(expr_type, ast.FieldType) or expr_type.name != "properties":
            return None
        field = expr_type.resolve_database_field(self.context)
        if not isinstance(field, DatabaseField) or field.name != "properties":
            return None
        table_type: ast.Type | None = expr_type.table_type
        while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType, ast.VirtualTableType)):
            table_type = table_type.table_type
        if not isinstance(table_type, ast.TableType):
            return None
        if table_type.table.to_printed_clickhouse(self.context) != "events":
            return None
        return table_type

    def _with_fallback(self, node: ast.PropertyAccess, function_name: str) -> ast.Expr:
        # The stored value wins whenever it is set; both NULL and '' mean "not set" for these string properties.
        def blob_read(key: str) -> ast.PropertyAccess:
            return ast.PropertyAccess(expr=clone_expr(node.expr), keys=[key], type=ast.StringType(nullable=True))

        def is_set(expr: ast.Expr) -> ast.Expr:
            return ast.Call(
                name="notEmpty",
                args=[ast.Call(name="ifNull", args=[expr, ast.Constant(value="")])],
                type=ast.BooleanType(),
            )

        # On a dictionary miss, fall back to the stored value rather than NULL, so blanks keep their existing
        # representation (materialized reads scrub '' to NULL, raw JSON reads return '' for a present-but-empty key).
        recovered = ast.Call(
            name="coalesce",
            args=[
                ast.Call(
                    name="nullIf",
                    args=[
                        ast.Call(name=function_name, args=[blob_read("$ip")], type=ast.StringType()),
                        ast.Constant(value=""),
                    ],
                    type=ast.StringType(nullable=True),
                ),
                clone_expr(node),
            ],
            type=ast.StringType(nullable=True),
        )
        guarded = ast.Call(
            name="if",
            args=[is_set(blob_read("$geoip_country_code")), recovered, clone_expr(node)],
            type=ast.StringType(nullable=True),
        )
        return ast.Call(
            name="if",
            args=[is_set(clone_expr(node)), clone_expr(node), guarded],
            type=ast.StringType(nullable=True),
        )


def apply_geoip_dict_fallback_delete_this_function_when_inc_2026_06_11_maxmind_missing_data_is_resolved(
    node: _T_AST, context: HogQLContext
) -> _T_AST:
    return cast(_T_AST, GeoipDictFallback(context).visit(node))
