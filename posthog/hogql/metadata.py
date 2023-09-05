from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import HogQLException
from posthog.hogql.hogql import translate_hogql
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast, create_hogql_database
from posthog.hogql.resolver import Resolver
from posthog.models import Team
from posthog.schema import HogQLMetadataResponse, HogQLMetadata, HogQLNotice
from posthog.hogql import ast
from posthog.warehouse.models import SavedQuery
from typing import Optional, List


def get_hogql_metadata(
    query: HogQLMetadata,
    team: Team,
) -> HogQLMetadataResponse:
    response = HogQLMetadataResponse(
        isValid=True,
        isValidView=False,
        inputExpr=query.expr,
        inputSelect=query.select,
        errors=[],
        warnings=[],
        notices=[],
    )

    try:
        if isinstance(query.expr, str):
            context = HogQLContext(team_id=team.pk)
            translate_hogql(query.expr, context=context)
        elif isinstance(query.select, str):
            context = HogQLContext(team_id=team.pk, enable_select_queries=True)
            context.database = create_hogql_database(context.team_id)
            select_ast = parse_select(query.select)
            _is_valid_view = is_valid_view(select_ast)

            # Kludge: redundant pass through the AST (called in print_ast)
            saved_query_visitor = SavedQueryVisitor(context=context)
            saved_query_visitor.visit(select_ast)

            # prevent nested views until optimized query building is implemented
            if _is_valid_view:
                if saved_query_visitor.has_saved_query:
                    raise HogQLException("Nested views are not supported")

                response.isValidView = _is_valid_view

            print_ast(node=select_ast, context=context, dialect="clickhouse", stack=None, settings=None)
        else:
            raise ValueError("Either expr or select must be provided")
        response.warnings = context.warnings
        response.notices = context.notices
    except Exception as e:
        response.isValid = False
        if isinstance(e, ValueError):
            response.errors.append(HogQLNotice(message=str(e)))
        elif isinstance(e, HogQLException):
            error = str(e)
            if "mismatched input '<EOF>' expecting" in error:
                error = "Unexpected end of query"
            response.errors.append(HogQLNotice(message=error, start=e.start, end=e.end))
        else:
            # We don't want to accidentally expose too much data via errors
            response.errors.append(HogQLNotice(message=f"Unexpected f{e.__class__.__name__}"))

    return response


def is_valid_view(select_query: ast.SelectQuery | ast.SelectUnionQuery) -> bool:
    for field in select_query.select:
        if not isinstance(field, ast.Alias):
            return False

    return True


class SavedQueryVisitor(Resolver):
    def __init__(self, context: HogQLContext, scopes: Optional[List[ast.SelectQueryType]] = None):
        super().__init__(context=context, scopes=scopes)
        self.has_saved_query = False

    def visit_join_expr(self, node: ast.JoinExpr):
        if isinstance(node.table, ast.Field):
            table_name = node.table.chain[0]
            if self.database.has_table(table_name):
                database_table = self.database.get_table(table_name)
                if isinstance(database_table, SavedQuery):
                    self.has_saved_query = True
        super().visit_join_expr(node)
