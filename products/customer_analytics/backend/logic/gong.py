from collections.abc import Sequence
from typing import cast
from urllib.parse import urlparse
from uuid import UUID

import structlog

from posthog.hogql import ast
from posthog.hogql.errors import QueryError
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.team import Team
from posthog.models.user import User

from products.customer_analytics.backend.models import Meeting
from products.warehouse_sources.backend.facade import (
    api as warehouse_sources,
    contracts as warehouse_contracts,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)


def _gong_calendar_event_id(meeting: Meeting) -> str:
    if meeting.recurrence_instance_id:
        return f"{meeting.ical_uid}_{meeting.recurrence_instance_id}"
    return meeting.ical_uid


def _gong_calls_tables(team_id: int) -> list[warehouse_contracts.DataWarehouseTable]:
    table_ids = {
        schema.table_id
        for source in warehouse_sources.list_sources(team_id)
        if source.source_type == ExternalDataSourceType.GONG
        for schema in warehouse_sources.list_schemas_for_source(source.id, team_id)
        if schema.name == "calls" and schema.should_sync and schema.table_id is not None
    }
    tables: list[warehouse_contracts.DataWarehouseTable] = []
    for table_id in sorted(table_ids, key=str):
        table = warehouse_sources.get_queryable_table(table_id, team_id)
        if table is not None and {"calendar_event_id", "url"}.issubset(table.columns):
            tables.append(table)
    return tables


def _valid_gong_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    hostname = parsed.hostname or ""
    if parsed.scheme != "https" or (hostname != "gong.io" and not hostname.endswith(".gong.io")):
        return None
    return value


def get_gong_urls_by_meeting_id(*, team: Team, user: User, meetings: Sequence[Meeting]) -> dict[UUID, str]:
    meetings_by_calendar_event_id = {_gong_calendar_event_id(meeting): meeting.id for meeting in meetings}
    if not meetings_by_calendar_event_id:
        return {}

    gong_urls: dict[UUID, str] = {}
    remaining_calendar_event_ids = set(meetings_by_calendar_event_id)
    for table in _gong_calls_tables(team.id):
        if not remaining_calendar_event_ids:
            break
        query = ast.SelectQuery(
            select=[ast.Field(chain=["calendar_event_id"]), ast.Field(chain=["url"])],
            select_from=ast.JoinExpr(table=ast.Field(chain=[table.name])),
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["calendar_event_id"]),
                right=ast.Constant(value=sorted(remaining_calendar_event_ids)),
            ),
            limit=ast.Constant(value=len(remaining_calendar_event_ids) * 10),
        )
        try:
            tag_queries(product=Product.CUSTOMER_ANALYTICS, feature=Feature.QUERY)
            response = execute_hogql_query(
                query=query,
                team=team,
                user=user,
                query_type="customer_analytics_gong_call_lookup",
            )
        except QueryError as error:
            logger.info(
                "gong_call_lookup_unavailable",
                team_id=team.id,
                table_id=str(table.id),
                error_type=type(error).__name__,
            )
            continue
        except Exception:
            logger.exception("gong_call_lookup_failed", team_id=team.id, table_id=str(table.id))
            continue

        rows = cast(list[list[object]], response.results or [])
        for calendar_event_id_value, url_value, *_ in rows:
            if not isinstance(calendar_event_id_value, str):
                continue
            meeting_id = meetings_by_calendar_event_id.get(calendar_event_id_value)
            gong_url = _valid_gong_url(url_value)
            if meeting_id is None or gong_url is None or meeting_id in gong_urls:
                continue
            gong_urls[meeting_id] = gong_url
            remaining_calendar_event_ids.discard(calendar_event_id_value)

    return gong_urls
