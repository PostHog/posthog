from typing import Any

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.hogql_queries.ai.ai_table_resolver import AIEventsExpiredError, AIEventsNotFoundError, query_ai_events
from posthog.models.team import Team

# A weekly batch job: every query must fail on its own rather than hold a worker slot for long.
MAX_EXECUTION_TIME_SECONDS = 60


def _settings() -> HogQLGlobalSettings:
    return HogQLGlobalSettings(max_execution_time=MAX_EXECUTION_TIME_SECONDS)


def run_query(team: Team, sql: str, placeholders: dict[str, ast.Expr], query_type: str) -> list[tuple[Any, ...]]:
    """Run HogQL against `events` (or any table other than `ai_events`). Nobody waits on the result."""
    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.EVAL_SUGGESTIONS, team_id=team.pk):
        response = execute_hogql_query(
            query=parse_select(sql, placeholders=placeholders),
            team=team,
            query_type=query_type,
            workload=Workload.OFFLINE,
            settings=_settings(),
        )
    return list(response.results or [])


def run_ai_events_query(
    team: Team, sql: str, placeholders: dict[str, ast.Expr], query_type: str
) -> list[tuple[Any, ...]]:
    """Run HogQL written against `ai_events`, the only table that keeps inputs and outputs.

    Placeholders go through the resolver, which rewrites `properties.$ai_*` reads onto native columns.
    An empty result is an empty list, whether the rows expired or never existed.
    """
    query = parse_select(sql)
    assert isinstance(query, ast.SelectQuery)
    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.EVAL_SUGGESTIONS, team_id=team.pk):
        try:
            response = query_ai_events(
                query=query,
                placeholders=placeholders,
                team=team,
                query_type=query_type,
                fall_back_to_events=False,
                workload=Workload.OFFLINE,
                settings=_settings(),
            )
        except (AIEventsNotFoundError, AIEventsExpiredError):
            return []
    return list(response.results or [])
