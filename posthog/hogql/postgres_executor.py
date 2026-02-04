"""
PostgreSQL query executor for HogQL queries.

This module provides functionality to execute HogQL queries against PostgreSQL
(Django models) with automatic access control injection.
"""

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from django.db import connection

import structlog

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.utils import prepare_ast_for_printing, print_prepared_ast

from posthog.models import OrganizationMembership
from posthog.rbac.user_access_control import UserAccessControl

if TYPE_CHECKING:
    from posthog.models import Team, User

logger = structlog.get_logger(__name__)


# Maximum number of rows to return from a query
MAX_ROWS = 1000


@dataclass
class PostgresQueryResult:
    """Result of a PostgreSQL query execution."""

    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool


class PostgresQueryExecutor:
    """
    Execute HogQL queries against PostgreSQL with access control.

    This executor:
    1. Parses HogQL into an AST
    2. Builds a context with user access control info
    3. Compiles to PostgreSQL with security guards injected
    4. Executes the query safely
    """

    def __init__(
        self,
        query: str,
        team: "Team",
        user: "User",
        *,
        limit: Optional[int] = None,
    ):
        self.query = query
        self.team = team
        self.user = user
        self.limit = min(limit or MAX_ROWS, MAX_ROWS)

    def execute(self) -> PostgresQueryResult:
        """
        Execute the HogQL query against PostgreSQL.

        Returns:
            PostgresQueryResult with columns, rows, and metadata
        """
        # Validate query is SELECT only
        self._validate_query()

        # Build context with user access control info
        context = self._build_context()

        # Parse and compile
        parsed = parse_select(self.query)
        prepared_ast = prepare_ast_for_printing(
            parsed,
            context=context,
            dialect="postgres",
        )
        sql = print_prepared_ast(
            prepared_ast,
            context=context,
            dialect="postgres",
        )

        logger.info(
            "Executing PostgreSQL query",
            team_id=self.team.id,
            user_id=self.user.id,
            query=self.query,
            compiled_sql=sql,
        )

        # Execute with safety limits
        return self._execute_sql(sql, context.values)

    def _validate_query(self) -> None:
        """Validate the query is safe to execute."""
        # Basic check for non-SELECT queries
        query_upper = self.query.strip().upper()
        if not query_upper.startswith("SELECT"):
            raise QueryError("Only SELECT queries are allowed")

        # Block dangerous keywords
        dangerous_keywords = ["INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER", "CREATE"]
        for keyword in dangerous_keywords:
            if keyword in query_upper:
                raise QueryError(f"{keyword} operations are not allowed")

    def _build_context(self) -> HogQLContext:
        """Build HogQL context with user access control information."""
        uac = UserAccessControl(user=self.user, team=self.team)
        org_membership = uac._organization_membership

        # Build database with Django tables
        database = self._build_database()

        return HogQLContext(
            team_id=self.team.id,
            team=self.team,
            database=database,
            enable_select_queries=True,
            limit_top_select=True,
            # Access control context
            user_id=self.user.id,
            is_org_admin=org_membership is not None and org_membership.level >= OrganizationMembership.Level.ADMIN,
            organization_membership_id=str(org_membership.id) if org_membership else None,
            role_ids=[str(role_id) for role_id in uac._user_role_ids] if uac._user_role_ids else [],
        )

    def _build_database(self) -> Database:
        """Build HogQL database including Django tables."""
        from posthog.hogql.database.database import Database
        from posthog.hogql.database.models import TableNode
        from posthog.hogql.database.schema.django_tables import get_django_tables

        # Create base database for the team
        database = Database(timezone=self.team.timezone, week_start_day=self.team.week_start_day)

        # Add Django tables
        django_tables = get_django_tables()
        for name, table in django_tables.items():
            database.tables.add_child(TableNode(name=name, table=table))

        return database

    def _execute_sql(self, sql: str, values: dict[str, Any]) -> PostgresQueryResult:
        """Execute the SQL query against PostgreSQL."""
        # Add LIMIT if not already present
        if "LIMIT" not in sql.upper():
            sql = f"{sql} LIMIT {self.limit + 1}"

        with connection.cursor() as cursor:
            cursor.execute(sql, values)
            columns = [col[0] for col in cursor.description]

            rows = []
            truncated = False
            for i, row in enumerate(cursor.fetchall()):
                if i >= self.limit:
                    truncated = True
                    break
                rows.append(dict(zip(columns, row)))

        return PostgresQueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
        )


def execute_postgres_query(
    query: str,
    team: "Team",
    user: "User",
    *,
    limit: Optional[int] = None,
) -> PostgresQueryResult:
    """
    Execute a HogQL query against PostgreSQL with access control.

    This is the main entry point for executing PostgreSQL queries.

    Args:
        query: HogQL query string
        team: Team to query for
        user: User making the query (for access control)
        limit: Maximum rows to return (default: 1000)

    Returns:
        PostgresQueryResult with query results
    """
    executor = PostgresQueryExecutor(query, team, user, limit=limit)
    return executor.execute()


def format_postgres_result_for_llm(result: PostgresQueryResult) -> str:
    """
    Format PostgreSQL query results for LLM consumption.

    Returns a JSON string with the results formatted for readability.
    """
    output = {
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
    }

    if result.truncated:
        output["truncated"] = True
        output["note"] = f"Results truncated to {result.row_count} rows"

    return json.dumps(output, default=str, indent=2)
