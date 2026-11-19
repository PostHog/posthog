"""Check that a user's access control lets them read everything a HogQL query selects from.

Enforcement lives in the schema: Database.create_for(user) leaves out tables and views the user
is denied, so resolving a query against it fails on anything they can't read - including tables
reached through nested views. Extracting table names and checking them individually would miss
those, so resolution is the only faithful definition of "what this query reads".
"""

from rest_framework import exceptions

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.schema.hog_invocation_results import HogInvocationResultsTable
from posthog.hogql.database.schema.log_entries import LogEntriesTable
from posthog.hogql.database.schema.logs import InternalLogsAccessTable
from posthog.hogql.errors import ExposedHogQLError, ResolutionError, TableAccessDeniedError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing
from posthog.hogql.visitor import TraversingVisitor

from posthog.models import User


def assert_user_can_read_sql(sql: str, team_id: int, user: User, database: Database | None = None) -> None:
    """Raise PermissionDenied unless `user` can read everything `sql` selects from.

    Raise ValidationError when `sql` does not resolve for a reason other than access.

    Pass `database` to reuse an already-built user-scoped schema; building one is the dominant
    cost, so callers checking several queries should build once and share it.
    """
    if not sql.strip():
        raise exceptions.ValidationError("Query is missing.")

    context = HogQLContext(team_id=team_id, user=user, enable_select_queries=True, database=database)
    try:
        # Resolution is where access is enforced, so this doesn't need to print.
        prepared = prepare_ast_for_printing(node=parse_select(sql), context=context, dialect="clickhouse")
    except TableAccessDeniedError as err:
        raise exceptions.PermissionDenied(str(err))
    except (ExposedHogQLError, ResolutionError) as err:
        # A query that no longer resolves, such as one reading a renamed column, can't be safely
        # published either, but the user is not denied anything, so it is a bad request.
        raise exceptions.ValidationError(str(err))

    # A published copy runs without the user, so the user's property rules would no longer hide pipeline rows.
    if context.restricted_properties and prepared is not None and _PipelineTableFinder.reads_pipeline_rows(prepared):
        raise exceptions.PermissionDenied(
            "Your property access permissions do not allow publishing queries that read pipeline logs."
        )


class _PipelineTableFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    @classmethod
    def reads_pipeline_rows(cls, node: ast.AST) -> bool:
        finder = cls()
        finder.visit(node)
        return finder.found

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        table_type = node.type
        while isinstance(table_type, ast.TableAliasType):
            table_type = table_type.table_type
        if isinstance(table_type, ast.TableType) and isinstance(
            table_type.table, (InternalLogsAccessTable, LogEntriesTable, HogInvocationResultsTable)
        ):
            self.found = True
        super().visit_join_expr(node)
