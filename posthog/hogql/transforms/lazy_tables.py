import dataclasses
from typing import Dict, List, Optional

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database import LazyJoin, LazyTable
from posthog.hogql.resolver import resolve_refs
from posthog.hogql.visitor import TraversingVisitor


def resolve_lazy_tables(node: ast.Expr, stack: Optional[List[ast.SelectQuery]] = None, context: HogQLContext = None):
    LazyTableResolver(stack=stack, context=context).visit(node)


@dataclasses.dataclass
class JoinToAdd:
    fields_accessed: Dict[str, ast.Expr]
    lazy_join: LazyJoin
    from_table: str
    to_table: str


@dataclasses.dataclass
class TableToAdd:
    fields_accessed: Dict[str, ast.Expr]
    lazy_table: LazyTable


class LazyTableResolver(TraversingVisitor):
    def __init__(self, stack: Optional[List[ast.SelectQuery]] = None, context: HogQLContext = None):
        super().__init__()
        self.stack_of_fields: List[List[ast.FieldRef | ast.PropertyRef]] = [[]] if stack else []
        self.context = context

    def _get_long_table_name(self, select: ast.SelectQueryRef, ref: ast.BaseTableRef) -> str:
        if isinstance(ref, ast.TableRef):
            return select.get_alias_for_table_ref(ref)
        elif isinstance(ref, ast.LazyTableRef):
            return ref.table.hogql_table()
        elif isinstance(ref, ast.TableAliasRef):
            return ref.name
        elif isinstance(ref, ast.SelectQueryAliasRef):
            return ref.name
        elif isinstance(ref, ast.LazyJoinRef):
            return f"{self._get_long_table_name(select, ref.table)}__{ref.field}"
        elif isinstance(ref, ast.VirtualTableRef):
            return f"{self._get_long_table_name(select, ref.table)}__{ref.field}"
        else:
            raise ValueError("Should not be reachable")

    def visit_property_ref(self, node: ast.PropertyRef):
        if node.joined_subquery is not None:
            # we have already visited this property
            return
        if isinstance(node.parent.table, ast.LazyJoinRef) or isinstance(node.parent.table, ast.LazyTableRef):
            if self.context and self.context.within_non_hogql_query:
                # If we're in a non-HogQL query, traverse deeper, just like we normally would have.
                self.visit(node.parent)
            else:
                # Place the property in a list for processing in "visit_select_query"
                if len(self.stack_of_fields) == 0:
                    raise ValueError("Can't access a lazy field when not in a SelectQuery context")
                self.stack_of_fields[-1].append(node)

    def visit_field_ref(self, node: ast.FieldRef):
        if isinstance(node.table, ast.LazyJoinRef) or isinstance(node.table, ast.LazyTableRef):
            # Each time we find a field, we place it in a list for processing in "visit_select_query"
            if len(self.stack_of_fields) == 0:
                raise ValueError("Can't access a lazy field when not in a SelectQuery context")
            self.stack_of_fields[-1].append(node)

    def visit_select_query(self, node: ast.SelectQuery):
        select_ref = node.ref
        if not select_ref:
            raise ValueError("Select query must have a ref")

        # Collect each `ast.Field` with `ast.LazyJoinRef`
        field_collector: List[ast.FieldRef] = []
        self.stack_of_fields.append(field_collector)

        # Collect all visited fields on lazy tables into field_collector
        super().visit_select_query(node)

        # Collect all the joins we need to add to the select query
        joins_to_add: Dict[str, JoinToAdd] = {}
        tables_to_add: Dict[str, TableToAdd] = {}

        # First properties, then fields. This way we always get the smallest units to query first.
        matched_properties: List[ast.PropertyRef | ast.FieldRef] = [
            property for property in field_collector if isinstance(property, ast.PropertyRef)
        ]
        matched_fields: List[ast.PropertyRef | ast.FieldRef] = [
            field for field in field_collector if isinstance(field, ast.FieldRef)
        ]
        sorted_properties: List[ast.PropertyRef | ast.FieldRef] = matched_properties + matched_fields

        for field_or_property in sorted_properties:
            if isinstance(field_or_property, ast.FieldRef):
                property = None
                field = field_or_property
            elif isinstance(field_or_property, ast.PropertyRef):
                property = field_or_property
                field = property.parent
            else:
                raise Exception("Should not be reachable")
            table_ref = field.table

            # Traverse the lazy tables until we reach a real table, collecting them in a list.
            # Usually there's just one or two.
            table_refs: List[ast.LazyJoinRef | ast.LazyTableRef] = []
            while isinstance(table_ref, ast.LazyJoinRef) or isinstance(table_ref, ast.LazyTableRef):
                table_refs.append(table_ref)
                table_ref = table_ref.table

            # Loop over the collected lazy tables in reverse order to create the joins
            for table_ref in reversed(table_refs):
                if isinstance(table_ref, ast.LazyJoinRef):
                    from_table = self._get_long_table_name(select_ref, table_ref.table)
                    to_table = self._get_long_table_name(select_ref, table_ref)
                    if to_table not in joins_to_add:
                        joins_to_add[to_table] = JoinToAdd(
                            fields_accessed={},  # collect here all fields accessed on this table
                            lazy_join=table_ref.lazy_join,
                            from_table=from_table,
                            to_table=to_table,
                        )
                    new_join = joins_to_add[to_table]
                    if table_ref == field.table:
                        chain = []
                        chain.append(field.name)
                        if property is not None:
                            chain.extend(property.chain)
                            property.joined_subquery_field_name = f"{field.name}___{'___'.join(property.chain)}"
                            new_join.fields_accessed[property.joined_subquery_field_name] = ast.Field(chain=chain)
                        else:
                            new_join.fields_accessed[field.name] = ast.Field(chain=chain)
                elif isinstance(table_ref, ast.LazyTableRef):
                    table_name = self._get_long_table_name(select_ref, table_ref)
                    if table_name not in tables_to_add:
                        tables_to_add[table_name] = TableToAdd(
                            fields_accessed={},  # collect here all fields accessed on this table
                            lazy_table=table_ref.table,
                        )
                    new_table = tables_to_add[table_name]
                    if table_ref == field.table:
                        chain = []
                        chain.append(field.name)
                        if property is not None:
                            chain.extend(property.chain)
                            property.joined_subquery_field_name = f"{field.name}___{'___'.join(property.chain)}"
                            new_table.fields_accessed[property.joined_subquery_field_name] = ast.Field(chain=chain)
                        else:
                            new_table.fields_accessed[field.name] = ast.Field(chain=chain)

        # Make sure we also add fields we will use for the join's "ON" condition into the list of fields accessed.
        # Without this "pdi.person.id" won't work if you did not ALSO select "pdi.person_id" explicitly for the join.
        for new_join in joins_to_add.values():
            if new_join.from_table in joins_to_add:
                joins_to_add[new_join.from_table].fields_accessed[new_join.lazy_join.from_field] = ast.Field(
                    chain=[new_join.lazy_join.from_field]
                )

        # For all the collected tables, create the subqueries, and add them to the table.
        for table_name, table_to_add in tables_to_add.items():
            subquery = table_to_add.lazy_table.lazy_select(table_to_add.fields_accessed)
            resolve_refs(subquery, self.context.database, select_ref)
            old_table_ref = select_ref.tables[table_name]
            select_ref.tables[table_name] = ast.SelectQueryAliasRef(name=table_name, ref=subquery.ref)

            join_ptr = node.select_from
            while join_ptr:
                if join_ptr.table.ref == old_table_ref:
                    join_ptr.table = subquery
                    join_ptr.ref = select_ref.tables[table_name]
                    join_ptr.alias = table_name
                    break
                join_ptr = join_ptr.next_join

        # For all the collected joins, create the join subqueries, and add them to the table.
        for to_table, join_scope in joins_to_add.items():
            join_to_add: ast.JoinExpr = join_scope.lazy_join.join_function(
                join_scope.from_table, join_scope.to_table, join_scope.fields_accessed
            )
            resolve_refs(join_to_add, self.context.database, select_ref)
            select_ref.tables[to_table] = join_to_add.ref

            join_ptr = node.select_from
            added = False
            while join_ptr:
                if join_scope.from_table == join_ptr.alias or (
                    isinstance(join_ptr.table, ast.Field) and join_scope.from_table == join_ptr.table.chain[0]
                ):
                    join_to_add.next_join = join_ptr.next_join
                    join_ptr.next_join = join_to_add
                    added = True
                    break
                if join_ptr.next_join:
                    join_ptr = join_ptr.next_join
                else:
                    break
            if not added:
                if join_ptr:
                    join_ptr.next_join = join_to_add
                elif node.select_from:
                    node.select_from.next_join = join_to_add
                else:
                    node.select_from = join_to_add

        # Assign all refs on the fields we collected earlier
        for field_or_property in field_collector:
            if isinstance(field_or_property, ast.FieldRef):
                table_ref = field_or_property.table
            elif isinstance(field_or_property, ast.PropertyRef):
                table_ref = field_or_property.parent.table
            else:
                raise Exception("Should not be reachable")

            table_name = self._get_long_table_name(select_ref, table_ref)
            table_ref = select_ref.tables[table_name]

            if isinstance(field_or_property, ast.FieldRef):
                field_or_property.table = table_ref
            elif isinstance(field_or_property, ast.PropertyRef):
                field_or_property.parent.table = table_ref
                field_or_property.joined_subquery = table_ref

        self.stack_of_fields.pop()
