import dataclasses
from typing import Callable, Dict, List, Optional, Set, Union

from posthog.hogql import ast
from posthog.hogql.resolver import resolve_symbols
from posthog.hogql.visitor import TraversingVisitor


def expand_asterisks(node: ast.Expr):
    AsteriskExpander().visit(node)


class AsteriskExpander(TraversingVisitor):
    def visit_select_query(self, node: ast.SelectQuery):
        columns: List[ast.Expr] = []
        for column in node.select:
            if isinstance(column.symbol, ast.AsteriskSymbol):
                asterisk = column.symbol
                if (
                    isinstance(asterisk.table, ast.TableSymbol)
                    or isinstance(asterisk.table, ast.TableAliasSymbol)
                    or isinstance(asterisk.table, ast.LazyTableSymbol)
                ):
                    table = asterisk.table
                    while isinstance(table, ast.TableAliasSymbol):
                        table = table.table
                    if isinstance(table, ast.TableSymbol):
                        database_fields = table.table.get_asterisk()
                        for key in database_fields.keys():
                            columns.append(
                                ast.Field(chain=[key], symbol=ast.FieldSymbol(name=key, table=asterisk.table))
                            )
                    elif isinstance(table, ast.LazyTableSymbol):
                        database_fields = table.joined_table.table.get_asterisk()
                        for key in database_fields.keys():
                            columns.append(
                                ast.Field(chain=[key], symbol=ast.FieldSymbol(name=key, table=asterisk.table))
                            )
                    else:
                        raise ValueError("Can't expand asterisk (*) on table")
                elif isinstance(asterisk.table, ast.SelectQuerySymbol) or isinstance(
                    asterisk.table, ast.SelectQueryAliasSymbol
                ):
                    select = asterisk.table
                    while isinstance(select, ast.SelectQueryAliasSymbol):
                        select = select.symbol
                    if isinstance(select, ast.SelectQuerySymbol):
                        for name in select.columns.keys():
                            columns.append(
                                ast.Field(chain=[name], symbol=ast.FieldSymbol(name=name, table=asterisk.table))
                            )
                    else:
                        raise ValueError("Can't expand asterisk (*) on subquery")
                else:
                    raise ValueError(f"Can't expand asterisk (*) on a symbol of type {type(asterisk.table).__name__}")

            else:
                columns.append(column)
        node.select = columns


def resolve_lazy_tables(node: ast.Expr, stack: Optional[List[ast.SelectQuery]] = None):
    if stack:
        # TODO: remove this kludge for old props
        LazyTableResolver(stack=stack).visit(stack[-1])
    LazyTableResolver(stack=stack).visit(node)


class LazyTableResolver(TraversingVisitor):
    def __init__(self, stack: Optional[List[ast.SelectQuery]] = None):
        super().__init__()
        self.stack_of_fields: List[List[ast.FieldSymbol]] = [[]] if stack else []

    def _get_long_table_name(
        self, select: ast.SelectQuerySymbol, symbol: Union[ast.TableSymbol, ast.LazyTableSymbol, ast.TableAliasSymbol]
    ) -> str:
        if isinstance(symbol, ast.TableSymbol):
            return select.key_for_table(symbol)
        elif isinstance(symbol, ast.TableAliasSymbol):
            return symbol.name
        elif isinstance(symbol, ast.LazyTableSymbol):
            return f"{self._get_long_table_name(select, symbol.table)}__{symbol.field}"
        else:
            raise ValueError("Should not be reachable")

    def visit_field_symbol(self, node: ast.FieldSymbol):
        if isinstance(node.table, ast.LazyTableSymbol):
            if len(self.stack_of_fields) == 0:
                raise ValueError("Can't access a lazy field when not in a SelectQuery context")
            self.stack_of_fields[-1].append(node)

    def visit_select_query(self, node: ast.SelectQuery):
        select_symbol = node.symbol
        if not select_symbol:
            raise ValueError("Select query must have a symbol")

        # Collects each `ast.Field` with `ast.LazyTableSymbol`
        field_collector: List[ast.FieldSymbol] = []
        self.stack_of_fields.append(field_collector)

        super().visit_select_query(node)

        @dataclasses.dataclass
        class JoinToAdd:
            fields_accessed: Set[str]
            join_function: Callable[[str, str, List[str]], ast.JoinExpr]
            from_table: str
            from_field: str
            to_table: str

        joins_to_add: Dict[str, JoinToAdd] = {}

        for field in field_collector:
            lazy_table = field.table
            # traverse the lazy tables to a real table, then loop over them in reverse order to create the joins
            joins_for_field: List = []
            while isinstance(lazy_table, ast.LazyTableSymbol):
                joins_for_field.append(lazy_table)
                lazy_table = lazy_table.table
            for lazy_table in reversed(joins_for_field):
                from_table = self._get_long_table_name(select_symbol, lazy_table.table)
                to_table = self._get_long_table_name(select_symbol, lazy_table)
                if to_table not in joins_to_add:
                    joins_to_add[to_table] = JoinToAdd(
                        fields_accessed=set(),
                        join_function=lazy_table.joined_table.join_function,
                        from_table=from_table,
                        from_field=lazy_table.joined_table.from_field,
                        to_table=to_table,
                    )
                new_join = joins_to_add[to_table]
                if lazy_table == field.table:
                    new_join.fields_accessed.add(field.name)

        # Make sure we also add the join "ON" condition fields into the list of fields accessed.
        # Without this "events.pdi.person.anything" won't work without ALSO selecting "events.pdi.person_id" explicitly
        for new_join in joins_to_add.values():
            if new_join.from_table in joins_to_add:
                joins_to_add[new_join.from_table].fields_accessed.add(new_join.from_field)

        last_join = node.select_from
        while last_join and last_join.next_join is not None:
            last_join = last_join.next_join

        for to_table, scope in joins_to_add.items():
            next_join = scope.join_function(scope.from_table, scope.to_table, list(scope.fields_accessed))
            resolve_symbols(next_join, select_symbol)
            select_symbol.tables[to_table] = next_join.symbol
            if last_join is None:
                node.select_from = next_join
                last_join = next_join
            else:
                last_join.next_join = next_join
            while last_join.next_join is not None:
                last_join = last_join.next_join

        for field in field_collector:
            to_table = self._get_long_table_name(select_symbol, field.table)
            field.table = select_symbol.tables[to_table]

        self.stack_of_fields.pop()
