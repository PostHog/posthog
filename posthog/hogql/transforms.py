import dataclasses
from typing import Callable, Dict, List, Set, Union

from posthog.hogql import ast
from posthog.hogql.resolver import resolve_symbols
from posthog.hogql.visitor import TraversingVisitor


def expand_splashes(node: ast.Expr):
    SplashExpander().visit(node)


class SplashExpander(TraversingVisitor):
    def visit_select_query(self, node: ast.SelectQuery):
        columns: List[ast.Expr] = []
        for column in node.select:
            if isinstance(column.symbol, ast.SplashSymbol):
                splash = column.symbol
                table = splash.table
                while isinstance(table, ast.TableAliasSymbol):
                    table = table.table
                if isinstance(table, ast.TableSymbol):
                    database_fields = table.table.get_splash()
                    for key in database_fields.keys():
                        columns.append(ast.Field(chain=[key], symbol=ast.FieldSymbol(name=key, table=splash.table)))
                elif isinstance(table, ast.LazyTableSymbol):
                    database_fields = table.joined_table.table.get_splash()
                    for key in database_fields.keys():
                        columns.append(ast.Field(chain=[key], symbol=ast.FieldSymbol(name=key, table=splash.table)))
                else:
                    raise ValueError("Can't expand splash (*) on subquery")
            else:
                columns.append(column)
        node.select = columns


def resolve_lazy_tables(node: ast.Expr):
    LazyTableResolver().visit(node)


class LazyTableResolver(TraversingVisitor):
    def __init__(self):
        super().__init__()
        self.fields: List[List[Union[ast.FieldSymbol]]] = []

    def visit_select_query(self, node: ast.SelectQuery):
        if not node.symbol:
            raise ValueError("Select query must have a symbol")

        # Collects each `ast.Field` with `ast.LazyTableSymbol`
        lazy_fields: List[Union[ast.FieldSymbol]] = []
        self.fields.append(lazy_fields)

        super().visit_select_query(node)

        last_join = node.select_from
        while last_join.next_join is not None:
            last_join = last_join.next_join

        @dataclasses.dataclass
        class LocalScope:
            fields_accessed: Set[str]
            join_function: Callable[[str, str, List[str]], ast.JoinExpr]
            parent_key: str
            table_alias: str

        new_tables: Dict[str, LocalScope] = {}

        for field in lazy_fields:
            if not isinstance(field.table, ast.LazyTableSymbol):
                raise ValueError("Should not be reachable.")
            parent_key = node.symbol.key_for_table(field.table.table)
            if parent_key is None:
                raise ValueError("Should not be reachable.")
            table_alias = f"{parent_key}_{field.table.field}"
            if not new_tables.get(table_alias):
                new_tables[table_alias] = LocalScope(
                    fields_accessed=set(),
                    join_function=field.table.joined_table.join_function,
                    parent_key=parent_key,
                    table_alias=table_alias,
                )
            new_tables[table_alias].fields_accessed.add(field.name)

        for table_alias, scope in new_tables.items():
            next_join = scope.join_function(scope.parent_key, scope.table_alias, list(scope.fields_accessed))
            resolve_symbols(next_join, node.symbol)
            node.symbol.tables[table_alias] = next_join.symbol  # type: ignore

            last_join.next_join = next_join
            while last_join.next_join is not None:
                last_join = last_join.next_join

        for field in lazy_fields:
            parent_key = node.symbol.key_for_table(field.table.table)
            table_alias = f"{parent_key}_{field.table.field}"
            field.table = node.symbol.tables[table_alias]

        self.fields.pop()

    def visit_field_symbol(self, node: ast.FieldSymbol):
        if isinstance(node.table, ast.LazyTableSymbol):
            if len(self.fields) == 0:
                raise ValueError("Can't access a lazy field when not in a SelectQuery context")
            self.fields[-1].append(node)
