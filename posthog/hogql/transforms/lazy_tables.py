import dataclasses
from typing import Dict, List, Optional, cast, Literal

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import LazyJoin, LazyTable
from posthog.hogql.errors import HogQLException
from posthog.hogql.resolver import resolve_types
from posthog.hogql.resolver_utils import get_long_table_name
from posthog.hogql.visitor import TraversingVisitor, clone_expr


def resolve_lazy_tables(
    node: ast.Expr,
    dialect: Literal["hogql", "clickhouse"],
    stack: Optional[List[ast.SelectQuery]] = None,
    context: HogQLContext = None,
):
    LazyTableResolver(stack=stack, context=context, dialect=dialect).visit(node)


@dataclasses.dataclass
class JoinToAdd:
    fields_accessed: Dict[str, List[str | int]]
    lazy_join: LazyJoin
    from_table: str
    to_table: str


@dataclasses.dataclass
class TableToAdd:
    fields_accessed: Dict[str, List[str | int]]
    lazy_table: LazyTable


@dataclasses.dataclass
class ConstraintOverride:
    alias: str
    table_name: str
    chain_to_replace: List[str | int]


class FieldChainReplacer(TraversingVisitor):
    overrides: List[ConstraintOverride] = {}

    def __init__(self, overrides: List[ConstraintOverride]) -> None:
        super().__init__()
        self.overrides = overrides

    def visit_field(self, node: ast.Field):
        for constraint in self.overrides:
            if node.chain == constraint.chain_to_replace:
                node.chain = [constraint.table_name, constraint.alias]


class LazyFinder(TraversingVisitor):
    found_lazy: bool = False

    def visit_lazy_join_type(self, node: ast.LazyJoinType):
        self.found_lazy = True

    def visit_lazy_table_type(self, node: ast.TableType):
        self.found_lazy = True


class LazyTableResolver(TraversingVisitor):
    lazy_finder_counter = 0

    def __init__(
        self,
        dialect: Literal["hogql", "clickhouse"],
        stack: Optional[List[ast.SelectQuery]] = None,
        context: HogQLContext = None,
    ):
        super().__init__()
        self.stack_of_fields: List[List[ast.FieldType | ast.PropertyType]] = [[]] if stack else []
        self.context = context
        self.dialect: Literal["hogql", "clickhouse"] = dialect

    def visit_property_type(self, node: ast.PropertyType):
        if node.joined_subquery is not None:
            # we have already visited this property
            return

        if isinstance(node.field_type.table_type, ast.TableAliasType):
            table_type: ast.TableOrSelectType | ast.TableAliasType = node.field_type.table_type.table_type
        else:
            table_type = node.field_type.table_type

        if isinstance(table_type, ast.LazyJoinType) or isinstance(table_type, ast.LazyTableType):
            if self.context and self.context.within_non_hogql_query:
                # If we're in a non-HogQL query, traverse deeper, just like we normally would have.
                self.visit(node.field_type)
            else:
                # Place the property in a list for processing in "visit_select_query"
                if len(self.stack_of_fields) == 0:
                    raise HogQLException("Can't access a lazy field when not in a SelectQuery context")
                self.stack_of_fields[-1].append(node)

    def visit_field_type(self, node: ast.FieldType):
        if isinstance(node.table_type, ast.TableAliasType):
            table_type: ast.TableOrSelectType | ast.TableAliasType = node.table_type.table_type
        else:
            table_type = node.table_type

        if isinstance(table_type, ast.LazyJoinType) or isinstance(table_type, ast.LazyTableType):
            # Each time we find a field, we place it in a list for processing in "visit_select_query"
            if len(self.stack_of_fields) == 0:
                raise HogQLException("Can't access a lazy field when not in a SelectQuery context")
            self.stack_of_fields[-1].append(node)

    def visit_select_query(self, node: ast.SelectQuery):
        select_type = node.type
        if not select_type:
            raise HogQLException("Select query must have a type")

        assert node.type is not None
        assert select_type is not None

        # Collect each `ast.Field` with `ast.LazyJoinType`
        field_collector: List[ast.FieldType | ast.PropertyType] = []
        self.stack_of_fields.append(field_collector)

        # Collect all visited fields on lazy tables into field_collector
        super().visit_select_query(node)

        # Collect all the joins we need to add to the select query
        joins_to_add: Dict[str, JoinToAdd] = {}
        tables_to_add: Dict[str, TableToAdd] = {}

        # First properties, then fields. This way we always get the smallest units to query first.
        matched_properties: List[ast.PropertyType | ast.FieldType] = [
            property for property in field_collector if isinstance(property, ast.PropertyType)
        ]
        matched_fields: List[ast.PropertyType | ast.FieldType] = [
            field for field in field_collector if isinstance(field, ast.FieldType)
        ]
        sorted_properties: List[ast.PropertyType | ast.FieldType] = matched_properties + matched_fields

        # Look for tables without requested fields to support cases like `select count() from table`
        join = node.select_from
        while join:
            if join.table is not None and isinstance(join.table.type, ast.LazyTableType):
                fields: List[ast.FieldType | ast.PropertyType] = []
                for field_or_property in field_collector:
                    if isinstance(field_or_property, ast.FieldType):
                        if isinstance(field_or_property.table_type, ast.TableAliasType):
                            if field_or_property.table_type.table_type == join.table.type:
                                fields.append(field_or_property)
                        else:
                            if field_or_property.table_type == join.table.type:
                                fields.append(field_or_property)
                    elif isinstance(field_or_property, ast.PropertyType):
                        if isinstance(field_or_property.field_type.table_type, ast.TableAliasType):
                            if field_or_property.field_type.table_type.table_type == join.table.type:
                                fields.append(field_or_property)
                        else:
                            if field_or_property.field_type.table_type == join.table.type:
                                fields.append(field_or_property)
                if len(fields) == 0:
                    table_name = join.alias or get_long_table_name(select_type, join.table.type)
                    tables_to_add[table_name] = TableToAdd(fields_accessed={}, lazy_table=join.table.type.table)
            join = join.next_join

        for field_or_property in sorted_properties:
            if isinstance(field_or_property, ast.FieldType):
                property = None
                field = field_or_property
            elif isinstance(field_or_property, ast.PropertyType):
                property = field_or_property
                field = property.field_type
            else:
                raise HogQLException("Should not be reachable")
            table_type = field.table_type

            # Traverse the lazy tables until we reach a real table, collecting them in a list.
            # Usually there's just one or two.
            table_types: List[ast.LazyJoinType | ast.LazyTableType | ast.TableAliasType] = []
            while (
                isinstance(table_type, ast.TableAliasType)
                or isinstance(table_type, ast.LazyJoinType)
                or isinstance(table_type, ast.LazyTableType)
            ):
                if isinstance(table_type, ast.TableAliasType):
                    table_types.append(table_type)
                    table_type = table_type.table_type
                    break
                if isinstance(table_type, ast.LazyJoinType):
                    table_types.append(table_type)
                    table_type = table_type.table_type
                if isinstance(table_type, ast.LazyTableType):
                    table_types.append(table_type)
                    break

            # Loop over the collected lazy tables in reverse order to create the joins
            for table_type in reversed(table_types):
                if isinstance(table_type, ast.LazyJoinType):
                    from_table = get_long_table_name(select_type, table_type.table_type)
                    to_table = get_long_table_name(select_type, table_type)
                    if to_table not in joins_to_add:
                        joins_to_add[to_table] = JoinToAdd(
                            fields_accessed={},  # collect here all fields accessed on this table
                            lazy_join=table_type.lazy_join,
                            from_table=from_table,
                            to_table=to_table,
                        )
                    new_join = joins_to_add[to_table]
                    if table_type == field.table_type:
                        chain: List[str | int] = []
                        chain.append(field.name)
                        if property is not None:
                            chain.extend(property.chain)
                            property.joined_subquery_field_name = (
                                f"{field.name}___{'___'.join(map(lambda x: str(x), property.chain))}"
                            )
                            new_join.fields_accessed[property.joined_subquery_field_name] = chain
                        else:
                            new_join.fields_accessed[field.name] = chain
                elif isinstance(table_type, ast.LazyTableType):
                    table_name = get_long_table_name(select_type, table_type)
                    if table_name not in tables_to_add:
                        tables_to_add[table_name] = TableToAdd(
                            fields_accessed={},  # collect here all fields accessed on this table
                            lazy_table=table_type.table,
                        )
                    new_table = tables_to_add[table_name]
                    if table_type == field.table_type:
                        chain = []
                        chain.append(field.name)
                        if property is not None:
                            chain.extend(property.chain)
                            property.joined_subquery_field_name = (
                                f"{field.name}___{'___'.join(map(lambda x: str(x), property.chain))}"
                            )
                            new_table.fields_accessed[property.joined_subquery_field_name] = chain
                        else:
                            new_table.fields_accessed[field.name] = chain
                elif isinstance(table_type, ast.TableAliasType):
                    if isinstance(table_type.table_type, ast.LazyJoinType):
                        from_table = get_long_table_name(select_type, table_type.table_type)
                        to_table = get_long_table_name(select_type, table_type)
                        if to_table not in joins_to_add:
                            joins_to_add[to_table] = JoinToAdd(
                                fields_accessed={},  # collect here all fields accessed on this table
                                lazy_join=table_type.table_type.lazy_join,
                                from_table=from_table,
                                to_table=to_table,
                            )
                        new_join = joins_to_add[to_table]
                        if table_type == field.table_type:
                            chain: List[str | int] = []
                            chain.append(field.name)
                            if property is not None:
                                chain.extend(property.chain)
                                property.joined_subquery_field_name = (
                                    f"{field.name}___{'___'.join(map(lambda x: str(x), property.chain))}"
                                )
                                new_join.fields_accessed[property.joined_subquery_field_name] = chain
                            else:
                                new_join.fields_accessed[field.name] = chain
                    elif isinstance(table_type.table_type, ast.LazyTableType):
                        table_name = get_long_table_name(select_type, table_type)
                        if table_name not in tables_to_add:
                            tables_to_add[table_name] = TableToAdd(
                                fields_accessed={},  # collect here all fields accessed on this table
                                lazy_table=cast(ast.LazyTable, table_type.table_type.table),
                            )
                        new_table = tables_to_add[table_name]
                        if table_type == field.table_type:
                            chain = []
                            chain.append(field.name)
                            if property is not None:
                                chain.extend(property.chain)
                                property.joined_subquery_field_name = (
                                    f"{field.name}___{'___'.join(map(lambda x: str(x), property.chain))}"
                                )
                                new_table.fields_accessed[property.joined_subquery_field_name] = chain
                            else:
                                new_table.fields_accessed[field.name] = chain

        # Make sure we also add fields we will use for the join's "ON" condition into the list of fields accessed.
        # Without this "pdi.person.id" won't work if you did not ALSO select "pdi.person_id" explicitly for the join.
        join_constraint_overrides: Dict[str, List[ConstraintOverride]] = {}

        def create_override(table_name: str, field_chain: List[str | int]) -> None:
            alias = f"{table_name}___{'___'.join(map(lambda x: str(x), field_chain))}"

            if table_name in tables_to_add:
                tables_to_add[table_name].fields_accessed[alias] = field_chain
            else:
                joins_to_add[table_name].fields_accessed[alias] = field_chain

            join_constraint_overrides[table_name] = [
                *join_constraint_overrides.get(table_name, []),
                ConstraintOverride(
                    alias=alias,
                    table_name=table_name,
                    chain_to_replace=[table_name, *field_chain],
                ),
            ]

        for new_join in joins_to_add.values():
            if new_join.from_table in joins_to_add or new_join.from_table in tables_to_add:
                create_override(new_join.from_table, new_join.lazy_join.from_field)
            if new_join.lazy_join.to_field is not None and (
                new_join.to_table in joins_to_add or new_join.to_table in tables_to_add
            ):
                create_override(new_join.to_table, new_join.lazy_join.to_field)

        # For all the collected tables, create the subqueries, and add them to the table.
        for table_name, table_to_add in tables_to_add.items():
            subquery = table_to_add.lazy_table.lazy_select(table_to_add.fields_accessed, self.context.modifiers)
            subquery = cast(ast.SelectQuery, clone_expr(subquery, clear_locations=True))
            subquery = cast(ast.SelectQuery, resolve_types(subquery, self.context, self.dialect, [node.type]))
            old_table_type = select_type.tables[table_name]
            select_type.tables[table_name] = ast.SelectQueryAliasType(alias=table_name, select_query_type=subquery.type)

            join_ptr = node.select_from
            while join_ptr:
                if join_ptr.table is not None and (
                    join_ptr.table.type == old_table_type
                    or (
                        isinstance(old_table_type, ast.TableAliasType)
                        and join_ptr.table.type == old_table_type.table_type
                    )
                ):
                    join_ptr.table = subquery
                    join_ptr.type = select_type.tables[table_name]
                    join_ptr.alias = table_name
                    break
                join_ptr = join_ptr.next_join

        # For all the collected joins, create the join subqueries, and add them to the table.
        for to_table, join_scope in joins_to_add.items():
            join_to_add: ast.JoinExpr = join_scope.lazy_join.join_function(
                join_scope.from_table,
                join_scope.to_table,
                join_scope.fields_accessed,
                self.context,
                node,
            )

            overrides = [
                *join_constraint_overrides.get(join_scope.to_table, []),
                *join_constraint_overrides.get(join_scope.from_table, []),
            ]
            if len(overrides) != 0:
                FieldChainReplacer(overrides).visit(join_to_add)

            join_to_add = cast(ast.JoinExpr, clone_expr(join_to_add, clear_locations=True, clear_types=True))
            join_to_add = cast(ast.JoinExpr, resolve_types(join_to_add, self.context, self.dialect, [node.type]))

            if join_to_add.type is not None:
                select_type.tables[to_table] = join_to_add.type

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

        # Assign all types on the fields we collected earlier
        for field_or_property in field_collector:
            if isinstance(field_or_property, ast.FieldType):
                table_type = field_or_property.table_type
            elif isinstance(field_or_property, ast.PropertyType):
                table_type = field_or_property.field_type.table_type
            else:
                raise HogQLException("Should not be reachable")

            table_name = get_long_table_name(select_type, table_type)
            table_type = select_type.tables[table_name]

            if isinstance(field_or_property, ast.FieldType):
                field_or_property.table_type = table_type
            elif isinstance(field_or_property, ast.PropertyType):
                field_or_property.field_type.table_type = table_type
                field_or_property.joined_subquery = table_type

        self.stack_of_fields.pop()

        # When joining a lazy table to another lazy table, the joined table doesn't get resolved
        # Doing another pass solves this for us
        if self.lazy_finder_counter < 20:
            lazy_finder = LazyFinder()
            lazy_finder.visit(node)
            if lazy_finder.found_lazy:
                self.lazy_finder_counter = self.lazy_finder_counter + 1
                self.visit_select_query(node)
