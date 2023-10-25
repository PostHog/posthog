from typing import List, Optional
from posthog.hogql import ast
from posthog.hogql.errors import HogQLException, ResolverException


def lookup_field_by_name(scope: ast.SelectQueryType, name: str) -> Optional[ast.Type]:
    """Looks for a field in the scope's list of aliases and children for each joined table."""
    if name in scope.aliases:
        return scope.aliases[name]
    else:
        named_tables = [table for table in scope.tables.values() if table.has_child(name)]
        anonymous_tables = [table for table in scope.anonymous_tables if table.has_child(name)]
        tables_with_field = named_tables + anonymous_tables

        if len(tables_with_field) > 1:
            raise ResolverException(f"Ambiguous query. Found multiple sources for field: {name}")
        elif len(tables_with_field) == 1:
            return tables_with_field[0].get_child(name)

        if scope.parent:
            return lookup_field_by_name(scope.parent, name)

        return None


def lookup_cte_by_name(scopes: List[ast.SelectQueryType], name: str) -> Optional[ast.CTE]:
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
    elif isinstance(type, ast.LazyJoinType):
        return f"{get_long_table_name(select, type.table_type)}__{type.field}"
    elif isinstance(type, ast.VirtualTableType):
        return f"{get_long_table_name(select, type.table_type)}__{type.field}"
    else:
        raise HogQLException(f"Unknown table type in LazyTableResolver: {type.__class__.__name__}")
