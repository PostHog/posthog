from typing import cast

from posthog.schema import AssistantHogQLQuery

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import (
    ExposedHogQLError,
    NotImplementedError as HogQLNotImplementedError,
    ResolutionError,
)
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import find_placeholders, replace_placeholders
from posthog.hogql.printer import prepare_and_print_ast

from posthog.models import Team
from posthog.sync import database_sync_to_async

from ee.hogai.context.insight.context import InsightContext


class HogQLValidationError(Exception):
    """Raised when HogQL query validation fails."""

    pass


def get_hogql_database(team: Team) -> Database:
    """Get the HogQL database for a team."""
    return Database.create_for(team=team)


def get_default_hogql_context(team: Team, database: Database) -> HogQLContext:
    """Get the default HogQL context for query compilation."""
    return HogQLContext(team=team, database=database, enable_select_queries=True)


def validate_hogql_sync(query: str, team: Team) -> AssistantHogQLQuery:
    """
    Validate a HogQL query synchronously.

    Args:
        query: The HogQL query string to validate.
        team: The team context for the query.

    Returns:
        A validated AssistantHogQLQuery object.

    Raises:
        HogQLValidationError: If the query is invalid.
    """
    cleaned_query = query.rstrip(";").strip() if query else ""
    if not cleaned_query:
        raise HogQLValidationError("Query is empty")

    database = get_hogql_database(team)
    hogql_context = get_default_hogql_context(team, database)

    try:
        parsed_query = parse_select(cleaned_query, placeholders={})

        # Replace placeholders with dummy values to compile the generated query.
        finder = find_placeholders(parsed_query)
        if finder.placeholder_fields or finder.has_filters:
            dummy_placeholders: dict[str, ast.Expr] = {
                str(field[0]): ast.Constant(value=1) for field in finder.placeholder_fields
            }
            if finder.has_filters:
                dummy_placeholders["filters"] = ast.Constant(value=1)
            parsed_query = cast(ast.SelectQuery, replace_placeholders(parsed_query, dummy_placeholders))

        prepare_and_print_ast(parsed_query, context=hogql_context, dialect="clickhouse")
    except (ExposedHogQLError, HogQLNotImplementedError, ResolutionError) as err:
        err_msg = str(err)
        if err_msg.startswith("no viable alternative"):
            err_msg = (
                'ANTLR parsing error: "no viable alternative at input". This means that the query isn\'t valid HogQL.'
            )
        raise HogQLValidationError(err_msg)

    return AssistantHogQLQuery(query=cleaned_query)


@database_sync_to_async(thread_sensitive=False)
def validate_hogql(query: str, team: Team) -> AssistantHogQLQuery:
    """
    Validate a HogQL query asynchronously.

    Args:
        query: The HogQL query string to validate.
        team: The team context for the query.

    Returns:
        A validated AssistantHogQLQuery object.

    Raises:
        HogQLValidationError: If the query is invalid.
    """
    return validate_hogql_sync(query, team)


async def execute_hogql_query(
    team: Team,
    query: AssistantHogQLQuery,
    name: str,
    description: str,
    insight_id: str | None = None,
) -> str:
    """
    Execute a HogQL query and format results.

    Args:
        team: The team context for the query.
        query: The validated HogQL query to execute.
        name: The name/title for the query visualization.
        description: The description for the query visualization.
        insight_id: Optional insight ID for linking.

    Returns:
        Formatted string result for LLM consumption.

    Raises:
        MaxToolRetryableError: If the query execution fails with a retryable error.
        Exception: For other unrecoverable errors.
    """
    insight_context = InsightContext(
        team=team,
        query=query,
        name=name,
        description=description,
        insight_id=insight_id,
    )
    return await insight_context.execute_and_format()
