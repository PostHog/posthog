from __future__ import annotations

from collections.abc import Generator
from typing import Optional

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    DecimalDatabaseField,
    ExpressionField,
    FieldOrTable,
    FieldTraverser,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringArrayDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
    UnknownDatabaseField,
    UUIDDatabaseField,
)
from posthog.hogql.errors import QueryError, ResolutionError, SyntaxError

from posthog import schema


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


def lookup_table_by_name(
    scope: ast.SelectQueryType, ctes: dict[str, ast.CTE], node: ast.Field
) -> Optional[ast.TableOrSelectType]:
    if len(node.chain) > 1 and str(node.chain[0]) in scope.tables:
        return scope.tables[str(node.chain[0])]

    if len(node.chain) > 1 and str(node.chain[0]) in ctes:
        cte = ctes[str(node.chain[0])]
        if isinstance(cte.type, ast.CTETableType):
            return cte.type.select_query_type

    return None


def lookup_cte_by_name(global_scopes: list[ast.SelectQueryType], name: str) -> Optional[ast.CTE]:
    for scope in global_scopes:
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
    elif isinstance(type, ast.CTETableType):
        return type.name
    elif isinstance(type, ast.CTETableAliasType):
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
    from posthog.hogql.visitor import clone_expr

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


def _constant_type_to_database_field(name: str, const_type: ast.ConstantType) -> DatabaseField:
    nullable = const_type.nullable

    if isinstance(const_type, ast.IntegerType):
        return IntegerDatabaseField(name=name, nullable=nullable)
    elif isinstance(const_type, ast.FloatType):
        return FloatDatabaseField(name=name, nullable=nullable)
    elif isinstance(const_type, ast.DecimalType):
        return DecimalDatabaseField(name=name, nullable=nullable)
    elif isinstance(const_type, ast.StringType):
        return StringDatabaseField(name=name, nullable=nullable)
    elif isinstance(const_type, ast.BooleanType):
        return BooleanDatabaseField(name=name, nullable=nullable)
    elif isinstance(const_type, ast.DateType):
        return DateDatabaseField(name=name, nullable=nullable)
    elif isinstance(const_type, ast.DateTimeType):
        return DateTimeDatabaseField(name=name, nullable=nullable)
    elif isinstance(const_type, ast.UUIDType):
        return UUIDDatabaseField(name=name, nullable=nullable)
    elif isinstance(const_type, ast.StringJSONType):
        return StringJSONDatabaseField(name=name, nullable=nullable)
    elif isinstance(const_type, ast.StringArrayType):
        return StringArrayDatabaseField(name=name, nullable=nullable)
    else:
        return UnknownDatabaseField(name=name, nullable=nullable)


def _recursively_resolve_column(
    name: str,
    column: ast.Type,
    fields: dict[str, FieldOrTable],
    context: HogQLContext,
) -> None:
    if isinstance(column, ast.FieldAliasType):
        return _recursively_resolve_column(name, column.type, fields, context)
    elif isinstance(column, ast.FieldType):
        db_field = column.resolve_database_field(context)
        if db_field:
            fields[name] = db_field
        else:
            const_type = column.resolve_constant_type(context)
            fields[name] = _constant_type_to_database_field(name, const_type)
    elif isinstance(column, ast.ExpressionFieldType):
        fields[name] = ExpressionField(name=column.name, expr=column.expr, isolate_scope=column.isolate_scope)
    elif isinstance(column, ast.FieldTraverserType):
        fields[name] = FieldTraverser(chain=column.chain)
    elif isinstance(column, ast.PropertyType):
        if column.joined_subquery and column.joined_subquery_field_name:
            select_type = column.joined_subquery.select_query_type
            if isinstance(select_type, ast.SelectSetQueryType):
                for t in select_type.types:
                    if isinstance(t, ast.SelectQueryType):
                        subquery_column = t.columns.get(column.joined_subquery_field_name)
                        if subquery_column:
                            return _recursively_resolve_column(name, subquery_column, fields, context)
            else:
                subquery_column = select_type.columns.get(column.joined_subquery_field_name)
                if subquery_column:
                    return _recursively_resolve_column(name, subquery_column, fields, context)

        return _recursively_resolve_column(name, column.field_type, fields, context)
    elif isinstance(column, ast.CallType):
        fields[name] = _constant_type_to_database_field(name, column.return_type)
    elif isinstance(column, ast.ConstantType):
        fields[name] = _constant_type_to_database_field(name, column)
    elif isinstance(column, ast.SelectQueryType):
        first_col = next(iter(column.columns.values()))
        return _recursively_resolve_column(name, first_col, fields, context)
    else:
        raise QueryError(f"{column.__class__.__name__} is not supported in CTETableType")


def resolve_cte_database_table(
    select_query_type: ast.SelectQueryType | ast.SelectSetQueryType,
    context: HogQLContext,
) -> Table:
    if isinstance(select_query_type, ast.SelectQueryType):
        columns = select_query_type.columns
    else:

        def recursively_get_columns(
            query_types: list[ast.SelectQueryType | ast.SelectSetQueryType],
        ) -> dict[str, ast.Type]:
            for t in query_types:
                if isinstance(t, ast.SelectQueryType):
                    return t.columns
                else:
                    return recursively_get_columns(t.types)
            raise QueryError("No select query type available")

        columns = recursively_get_columns(select_query_type.types)

    fields: dict[str, FieldOrTable] = {}

    for name, column in columns.items():
        _recursively_resolve_column(name, column, fields, context)

    return Table(fields=fields)
