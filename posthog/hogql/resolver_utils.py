from typing import Optional
from collections.abc import Generator

from posthog import schema
from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ResolutionError, SyntaxError
from posthog.hogql.visitor import clone_expr


def lookup_field_by_name(
    scope: ast.SelectQueryType | ast.SelectSetQueryType, name: str, context: HogQLContext
) -> Optional[ast.Type]:
    """Looks for a field in the scope's list of aliases and children for each joined table."""

    if isinstance(scope, ast.SelectSetQueryType):
        field: Optional[ast.Type] = None
        for type in scope.types:
            new_field = lookup_field_by_name(type, name, context)
            if new_field:
                if field:
                    raise ResolutionError(f"Ambiguous query. Found multiple sources for field: {name}")
                field = new_field
        return field

    if name in scope.aliases:
        return scope.aliases[name]
    else:
        named_tables = [table for table in scope.tables.values() if table.has_child(name, context)]
        anonymous_tables = [table for table in scope.anonymous_tables if table.has_child(name, context)]
        tables_with_field = named_tables + anonymous_tables

        if len(tables_with_field) > 1:
            raise ResolutionError(f"Ambiguous query. Found multiple sources for field: {name}")
        elif len(tables_with_field) == 1:
            return tables_with_field[0].get_child(name, context)

        if scope.parent:
            return lookup_field_by_name(scope.parent, name, context)

        return None


def lookup_cte_by_name(scopes: list[ast.SelectQueryType], name: str) -> Optional[ast.CTE]:
    for scope in reversed(scopes):
        if scope and scope.ctes and name in scope.ctes:
            return scope.ctes[name]
    return None


def get_long_table_name(select: ast.SelectQueryType, type: ast.Type) -> str:
    if isinstance(type, ast.TableType):
        return select.get_alias_for_table_type(type) or ""
    elif isinstance(type, ast.LazyTableType):
        return type.table.to_printed_hogql()
    elif isinstance(type, ast.TableAliasType):
        return type.alias
    elif isinstance(type, ast.SelectQueryAliasType):
        return type.alias
    elif isinstance(type, ast.SelectViewType):
        return type.alias
    elif isinstance(type, ast.LazyJoinType):
        return f"{get_long_table_name(select, type.table_type)}__{type.field}"
    elif isinstance(type, ast.VirtualTableType):
        return f"{get_long_table_name(select, type.table_type)}__{type.field}"
    else:
        raise ResolutionError(f"Unknown table type in LazyTableResolver: {type.__class__.__name__}")


def ast_to_query_node(expr: ast.Expr | ast.HogQLXTag):
    if isinstance(expr, ast.Constant):
        return expr.value
    elif isinstance(expr, ast.Array):
        return [ast_to_query_node(e) for e in expr.exprs]
    elif isinstance(expr, ast.Tuple):
        return tuple(ast_to_query_node(e) for e in expr.exprs)
    elif isinstance(expr, ast.HogQLXTag):
        for klass in schema.__dict__.values():
            if isinstance(klass, type) and issubclass(klass, schema.BaseModel) and klass.__name__ == expr.kind:
                attributes = expr.to_dict()
                attributes.pop("kind")
                # Query runners use "source" instead of "children" for their source query
                if "children" in attributes and "source" in klass.model_fields:
                    attributes["source"] = attributes.pop("children")[0]
                new_attributes = {key: ast_to_query_node(value) for key, value in attributes.items()}
                return klass(**new_attributes)
        raise SyntaxError(f"Unknown tag <{expr.kind} />.")
    else:
        raise SyntaxError(f'Expression of type "{type(expr).__name__}". Can\'t convert to constant.')


def expand_hogqlx_query(node: ast.HogQLXTag, team_id: Optional[int]):
    from posthog.hogql_queries.query_runner import get_query_runner
    from posthog.models import Team

    if team_id is None:
        raise ResolutionError("team_id is required to convert a query tag to a query", start=node.start, end=node.end)

    try:
        query_node = ast_to_query_node(node)
        runner = get_query_runner(query_node, Team.objects.get(pk=team_id))
        query = clone_expr(runner.to_query(), clear_locations=True)
        return query
    except Exception as e:
        raise ResolutionError(f"Error parsing query tag: {e}", start=node.start, end=node.end)


def extract_select_queries(select: ast.SelectSetQuery | ast.SelectQuery) -> Generator[ast.SelectQuery, None, None]:
    if isinstance(select, ast.SelectQuery):
        yield select
    else:
        yield from extract_select_queries(select.initial_select_query)
        for select_query in select.subsequent_select_queries:
            yield from extract_select_queries(select_query.select_query)
