"""How far a source's Kafka ingestion has reached, read from its per-partition consumption table.

A source's consumption table (`logs_kafka_metrics`, `trace_spans_kafka_metrics`) keeps the newest
observed timestamp each partition has written. The slowest partition bounds what every team can read,
because the table is not team-scoped.
"""

import datetime as dt
from collections.abc import Sequence
from typing import Final
from zoneinfo import ZoneInfo

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.visitor import clone_expr

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Team

# minOrNull, because min over no rows returns the epoch rather than NULL.
_CHECKPOINT_QUERY: Final = parse_select(
    """
    SELECT minOrNull(partition_checkpoint) FROM (
        SELECT _topic, _partition, max(max_observed_timestamp) AS partition_checkpoint
        FROM consumption_table
        GROUP BY _topic, _partition
    )
    """
)


def fetch_ingestion_checkpoint(
    team: Team,
    *,
    consumption_table: Sequence[str],
    product: Product,
    source: str,
    ch_user: ClickHouseUser = ClickHouseUser.DEFAULT,
    max_execution_time: int | None = None,
) -> dt.datetime | None:
    """The newest timestamp every ingestion partition has passed, or None before anything was consumed.

    `consumption_table` is the HogQL table chain, such as `("logs_kafka_metrics",)`.
    """
    query = clone_expr(_CHECKPOINT_QUERY, clear_types=True)
    assert isinstance(query, ast.SelectQuery) and query.select_from is not None
    inner = query.select_from.table
    assert isinstance(inner, ast.SelectQuery) and inner.select_from is not None
    inner.select_from.table = ast.Field(chain=list(consumption_table))

    tag_queries(product=product, feature=Feature.ALERTING, source=source, team_id=str(team.id))
    response = execute_hogql_query(
        query_type="alert_check_checkpoint",
        query=query,
        team=team,
        workload=Workload.LOGS,
        ch_user=ch_user,
        modifiers=HogQLQueryModifiers(convertToProjectTimezone=False),
        settings=None
        if max_execution_time is None
        else HogQLGlobalSettings(max_execution_time=max_execution_time, timeout_overflow_mode="throw"),
    )
    if not response.results or response.results[0][0] is None:
        return None
    checkpoint: dt.datetime = response.results[0][0]
    return checkpoint if checkpoint.tzinfo is not None else checkpoint.replace(tzinfo=ZoneInfo("UTC"))
