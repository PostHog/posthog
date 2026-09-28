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

from datetime import datetime
from typing import Any, Optional

from django.db.models import Q

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.log_entries import LOG_ENTRIES_SHARDED_TABLE, LOG_ENTRIES_TABLE
from posthog.dataclasses import frozen
from posthog.settings import CLICKHOUSE_DATABASE

from products.cdp.backend.models.hog_functions.hog_function import HogFunction

DESTINATION_TEMPLATE_PREFIXES = ("segment-", "native-")

# The executors log these as `addLog('debug', '<name>', object)`, which the log
# sanitizer renders as `<name>, {...json...}`.
DEBUG_LOG_PREFIXES = ("config, {", "options, {", "headers, {", "requestExtension, {", "fetchOptions, {")


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


def _data_table() -> str:
    # Production holds the rows in `sharded_log_entries`; the test schema has no such table.
    rows = sync_execute(
        "SELECT count() FROM system.tables WHERE database = %(database)s AND name = %(name)s",
        {"database": CLICKHOUSE_DATABASE, "name": LOG_ENTRIES_SHARDED_TABLE},
    )
    return LOG_ENTRIES_SHARDED_TABLE if rows[0][0] else LOG_ENTRIES_TABLE


def delete_debug_logs(scope: DebugLogScope, functions: list[tuple[int, str]], wait: bool = False) -> None:
    if not functions:
        return
    # Waiting on every replica outlasts the client timeout in production, so it runs asynchronously.
    sync_execute(
        f"""
        DELETE FROM {_data_table()} {ON_CLUSTER_CLAUSE()}
        WHERE {_predicate()}
        """,
        _args(scope, functions),
        settings={"lightweight_deletes_sync": 2 if wait else 0},
    )
