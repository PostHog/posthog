"""Delete the debug log lines in which native and segment destinations dumped their
resolved inputs and request options in plain text.

With debug mode on, both executors logged `config`, `options`, `headers`,
`requestExtension` and `fetchOptions` as raw JSON, so integration credentials and
secret inputs landed in `log_entries`, readable by any member of the project.
The executors redact these lines now, and this removes the lines written before
that, which otherwise stay until the table's 90 day TTL.

Scoped to the functions built on those executors, matched by template prefix,
and to lines older than the cutoff the operator passes, so redacted lines written
after the fix are never touched.
"""

import re
from datetime import datetime
from typing import Any, Optional

from django.db.models import Q

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.execute import default_settings, sync_execute
from posthog.clickhouse.client.migration_tools import collapses_to_all_nodes, get_migrations_cluster
from posthog.clickhouse.log_entries import LOG_ENTRIES_DATA_TABLE, LOG_ENTRIES_TABLE
from posthog.dataclasses import frozen
from posthog.settings import CLICKHOUSE_AUX_CLUSTER, CLICKHOUSE_DATABASE

from products.cdp.backend.models.hog_functions.hog_function import HogFunction

DESTINATION_TEMPLATE_PREFIXES = ("segment-", "native-")

# The executors log these as `addLog('debug', '<name>', object)`, which the log
# sanitizer renders as `<name>, {...json...}`.
DEBUG_LOG_PREFIXES = ("config, {", "options, {", "headers, {", "requestExtension, {", "fetchOptions, {")

# The cluster, database and table arguments of a Distributed engine, as `system.tables.engine_full` renders them.
DISTRIBUTED_TARGET = re.compile(r"^Distributed\('([^']*)', '([^']*)', '([^']*)'")


@frozen
class DebugLogScope:
    before: datetime
    team_id: Optional[int] = None


@frozen
class DebugLogCount:
    lines: int
    functions: int
    teams: int
    first_seen: Optional[datetime]
    last_seen: Optional[datetime]


def find_destination_functions(scope: DebugLogScope) -> list[tuple[int, str]]:
    # Deleted functions keep their logs, so they stay in scope.
    template_filter = Q()
    for prefix in DESTINATION_TEMPLATE_PREFIXES:
        template_filter |= Q(template_id__startswith=prefix)
    queryset = HogFunction.objects.filter(template_filter)
    if scope.team_id is not None:
        queryset = queryset.filter(team_id=scope.team_id)
    return [(team_id, str(function_id)) for team_id, function_id in queryset.values_list("team_id", "id")]


def _predicate() -> str:
    message_filter = " OR ".join(f"message LIKE %(prefix_{i})s" for i in range(len(DEBUG_LOG_PREFIXES)))
    # `(team_id, log_source_id)` is the primary key prefix, so the pair list prunes parts.
    return f"""
        log_source = 'hog_function'
        AND level = 'debug'
        AND (team_id, log_source_id) IN %(functions)s
        AND timestamp < %(before)s
        AND ({message_filter})
    """


def _args(scope: DebugLogScope, functions: list[tuple[int, str]]) -> dict[str, Any]:
    args: dict[str, Any] = {"functions": functions, "before": scope.before}
    for i, prefix in enumerate(DEBUG_LOG_PREFIXES):
        args[f"prefix_{i}"] = f"{prefix}%"
    return args


def count_debug_logs(scope: DebugLogScope, functions: list[tuple[int, str]]) -> DebugLogCount:
    if not functions:
        return DebugLogCount(lines=0, functions=0, teams=0, first_seen=None, last_seen=None)
    # nosemgrep: clickhouse-fstring-param-audit - only constants are interpolated; scope and functions are bound parameters
    rows = sync_execute(
        f"""
        SELECT count(), uniqExact(log_source_id), uniqExact(team_id), min(timestamp), max(timestamp)
        FROM {LOG_ENTRIES_TABLE}
        WHERE {_predicate()}
        """,
        _args(scope, functions),
    )
    lines, function_count, teams, first_seen, last_seen = rows[0]
    return DebugLogCount(
        lines=lines,
        functions=function_count,
        teams=teams,
        first_seen=first_seen if lines else None,
        last_seen=last_seen if lines else None,
    )


def _log_entries_reads_aux() -> bool:
    # Deployed regions and fresh environments read `log_entries` through a Distributed table over
    # `log_entries_data` on the aux cluster. The test schema keeps the rows in a local `log_entries` MergeTree.
    rows = sync_execute(
        "SELECT engine_full FROM system.tables WHERE database = %(database)s AND name = %(name)s",
        {"database": CLICKHOUSE_DATABASE, "name": LOG_ENTRIES_TABLE},
    )
    engine_full = rows[0][0] if rows else ""
    if not engine_full.startswith("Distributed("):
        return False
    target = DISTRIBUTED_TARGET.match(engine_full)
    if target and target.groups() == (CLICKHOUSE_AUX_CLUSTER, CLICKHOUSE_DATABASE, LOG_ENTRIES_DATA_TABLE):
        return True
    # Deleting from aux while reads come from elsewhere would leave the lines readable, so refuse.
    raise RuntimeError(
        f"`{LOG_ENTRIES_TABLE}` reads {engine_full}, not `{LOG_ENTRIES_DATA_TABLE}` on the aux cluster. Nothing was deleted."
    )


def delete_debug_logs(scope: DebugLogScope, functions: list[tuple[int, str]], wait: bool = False) -> None:
    if not functions:
        return
    args = _args(scope, functions)
    # Waiting on every replica outlasts the client timeout in production, so it runs asynchronously.
    delete_settings = {"lightweight_deletes_sync": 2 if wait else 0}
    if not _log_entries_reads_aux():
        # nosemgrep: clickhouse-fstring-param-audit - only constants are interpolated; scope and functions are bound parameters
        sync_execute(f"DELETE FROM {LOG_ENTRIES_TABLE} WHERE {_predicate()}", args, settings=delete_settings)
        return
    # nosemgrep: clickhouse-fstring-param-audit - only constants are interpolated; scope and functions are bound parameters
    sql = f"DELETE FROM {LOG_ENTRIES_DATA_TABLE} WHERE {_predicate()}"
    if collapses_to_all_nodes():
        # Single-node installs hold `log_entries_data` on the one node, which carries no aux role.
        sync_execute(sql, args, settings=delete_settings)
        return
    # The aux cluster is a single shard: one host runs the delete and replication carries it.
    # The raw client skips sync_execute's defaults, and a region-wide function list needs their larger max_query_size.
    client_settings = {**default_settings(), **delete_settings}
    get_migrations_cluster().any_host_by_role(
        lambda client: client.execute(sql, args, settings=client_settings), NodeRole.AUX
    ).result()
