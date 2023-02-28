import dataclasses
from typing import Dict, List, Optional, Set

from posthog.hogql import ast
from posthog.hogql.ast import LazyTableSymbol
from posthog.hogql.database import LazyTable
from posthog.hogql.resolver import resolve_symbols
from posthog.hogql.visitor import TraversingVisitor


def resolve_lazy_tables(node: ast.Expr, stack: Optional[List[ast.SelectQuery]] = None):
    if stack:
        # TODO: remove this kludge for old props
        LazyTableResolver(stack=stack).visit(stack[-1])
    LazyTableResolver(stack=stack).visit(node)


@dataclasses.dataclass
class JoinToAdd:
    fields_accessed: Set[str]
    lazy_table: LazyTable
    from_table: str
    to_table: str


class LazyTableResolver(TraversingVisitor):
    def __init__(self, stack: Optional[List[ast.SelectQuery]] = None):
        super().__init__()
        self.stack_of_fields: List[List[ast.FieldSymbol]] = [[]] if stack else []

    def _get_long_table_name(self, select: ast.SelectQuerySymbol, symbol: ast.BaseTableSymbol) -> str:
        if isinstance(symbol, ast.TableSymbol):
            return select.get_alias_for_table_symbol(symbol)
        elif isinstance(symbol, ast.TableAliasSymbol):
            return symbol.name
        elif isinstance(symbol, ast.SelectQueryAliasSymbol):
            return symbol.name
        elif isinstance(symbol, ast.LazyTableSymbol):
            return f"{self._get_long_table_name(select, symbol.table)}__{symbol.field}"
        elif isinstance(symbol, ast.VirtualTableSymbol):
            return f"{self._get_long_table_name(select, symbol.table)}__{symbol.field}"
        else:
            raise ValueError("Should not be reachable")

    def visit_field_symbol(self, node: ast.FieldSymbol):
        if isinstance(node.table, ast.LazyTableSymbol):
            # Each time we find a field, we place it in a list for processing in "visit_select_query"
            if len(self.stack_of_fields) == 0:
                raise ValueError("Can't access a lazy field when not in a SelectQuery context")
            self.stack_of_fields[-1].append(node)

    def visit_select_query(self, node: ast.SelectQuery):
        select_symbol = node.symbol
        if not select_symbol:
            raise ValueError("Select query must have a symbol")

        # Collect each `ast.Field` with `ast.LazyTableSymbol`
        field_collector: List[ast.FieldSymbol] = []
        self.stack_of_fields.append(field_collector)

        # Collect all visited fields on lazy tables into field_collector
        super().visit_select_query(node)

        # Collect all the joins we need to add to the select query
        joins_to_add: Dict[str, JoinToAdd] = {}
        for field in field_collector:
            table_symbol = field.table

            # Traverse the lazy tables until we reach a real table, collecting them in a list.
            # Usually there's just one or two.
            table_symbols: List[LazyTableSymbol] = []
            while isinstance(table_symbol, ast.LazyTableSymbol):
                table_symbols.append(table_symbol)
                table_symbol = table_symbol.table

            # Loop over the collected lazy tables in reverse order to create the joins
            for table_symbol in reversed(table_symbols):
                from_table = self._get_long_table_name(select_symbol, table_symbol.table)
                to_table = self._get_long_table_name(select_symbol, table_symbol)
                if to_table not in joins_to_add:
                    joins_to_add[to_table] = JoinToAdd(
                        fields_accessed=set(),  # collect here all fields accessed on this table
                        lazy_table=table_symbol.lazy_table,
                        from_table=from_table,
                        to_table=to_table,
                    )
                new_join = joins_to_add[to_table]
                if table_symbol == field.table:
                    new_join.fields_accessed.add(field.name)

        # Make sure we also add fields we will use for the join's "ON" condition into the list of fields accessed.
        # Without thi "pdi.person.id" won't work if you did not ALSO select "pdi.person_id" explicitly for the join.
        for new_join in joins_to_add.values():
            if new_join.from_table in joins_to_add:
                joins_to_add[new_join.from_table].fields_accessed.add(new_join.lazy_table.from_field)

        # Move the "last_join" pointer to the last join in the SELECT query
        last_join = node.select_from
        while last_join and last_join.next_join is not None:
            last_join = last_join.next_join

        # For all the collected joins, create the join subqueries, and add them to the table.
        for to_table, scope in joins_to_add.items():
            next_join = scope.lazy_table.join_function(
                scope.from_table, scope.to_table, sorted(list(scope.fields_accessed))
            )
            resolve_symbols(next_join, select_symbol)
            select_symbol.tables[to_table] = next_join.symbol

            # Link up the joins properly
            if last_join is None:
                node.select_from = next_join
                last_join = next_join
            else:
                last_join.next_join = next_join
            while last_join.next_join is not None:
                last_join = last_join.next_join

        # Assign all symbols on the fields we collected earlier
        for field in field_collector:
            to_table = self._get_long_table_name(select_symbol, field.table)
            field.table = select_symbol.tables[to_table]

        self.stack_of_fields.pop()
