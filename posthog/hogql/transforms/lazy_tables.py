import dataclasses
from typing import Optional, cast

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import LazyJoinToAdd, LazyTableToAdd
from posthog.hogql.errors import ResolutionError
from posthog.hogql.resolver import ResolverFactory, resolve_types
from posthog.hogql.resolver_utils import get_long_table_name
from posthog.hogql.transforms.logical_property_lowering import lower_property_access
from posthog.hogql.transforms.property_types import PropertySwapper
from posthog.hogql.visitor import TraversingVisitor, clone_expr

from posthog.dataclasses import frozen


# This mutates the nodes
def resolve_lazy_tables(
    node: _T_AST,
    dialect: HogQLDialect,
    stack: Optional[list[ast.SelectQuery]],
    context: HogQLContext,
    resolver_factory: ResolverFactory | None = None,
):
    LazyTableResolver(stack=stack, context=context, dialect=dialect, resolver_factory=resolver_factory).visit(node)


@dataclasses.dataclass
class ConstraintOverride:
    alias: str
    table_name: str
    chain_to_replace: list[str | int]


class FieldChainReplacer(TraversingVisitor):
    overrides: list[ConstraintOverride] = []

    def __init__(self, overrides: list[ConstraintOverride]) -> None:
        super().__init__()
        self.overrides = overrides

    def visit_field(self, node: ast.Field):
        for constraint in self.overrides:
            if node.chain == constraint.chain_to_replace:
                node.chain = [constraint.table_name, constraint.alias]


class FieldFinder(TraversingVisitor):
    field_chains: list[list[str | int]] = []

    def __init__(self) -> None:
        super().__init__()
        self.field_chains = []

    def visit_field(self, node: ast.Field):
        self.field_chains.append(node.chain)


def find_field_chains(node: ast.AST | None) -> list[list[str | int]]:
    if node is None:
        return []
    finder = FieldFinder()
    finder.visit(node)
    return finder.field_chains


def get_table_alias_for_lazy_join(lazy_join_type: ast.LazyJoinType) -> str | None:
    table_type = lazy_join_type.table_type
    while table_type:
        if isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
            return table_type.alias
        if isinstance(table_type, ast.TableType):
            # No alias, use the table name directly
            return table_type.table.to_printed_hogql()
        if isinstance(table_type, (ast.VirtualTableType, ast.LazyJoinType)):
            table_type = table_type.table_type
        else:
            break
    return None


def _hops_to_table(
    table_type: ast.Type, table: ast.TableOrSelectType
) -> list[ast.LazyJoinType | ast.VirtualTableType] | None:
    """The lazy-join and virtual-table hops from `table` down to `table_type`, outermost first.

    None when `table_type` is not bound to `table`. The same alias in a nested query is a different binding object,
    so identity keeps the two apart where a name comparison would not.
    """
    hops: list[ast.LazyJoinType | ast.VirtualTableType] = []
    current: ast.Type = table_type
    while current is not table:
        if not isinstance(current, (ast.LazyJoinType, ast.VirtualTableType)):
            return None
        hops.append(current)
        current = current.table_type
    hops.reverse()
    return hops


@frozen
class WrappedTableExport:
    """One column of the subquery that replaces a joined table."""

    name: str
    # The field the subquery selects from the original table, without the table alias: a column, or the document a
    # property is read from, through any virtual-table and lazy-join hops.
    field_chain: tuple[str, ...]
    # The key path read from that document. It is applied after resolution so an integer array index stays an integer.
    property_path: tuple[str | int, ...]
    # Lower the read to an unconverted `PropertyAccess`, so the outer read keeps its own conversion context.
    raw_property: bool


class WrappedTableReferenceCollector(TraversingVisitor):
    """Collects the outer reads of one table binding before a subquery replaces that table.

    Reads are matched by their resolved binding rather than by the alias they were written with. That includes the
    unqualified reads an expression field expands to, and reads through the table's virtual tables and lazy joins,
    and it excludes a nested query's alias of the same name.
    """

    def __init__(self, table: ast.TableOrSelectType) -> None:
        super().__init__()
        self.table = table
        self.exports: dict[str, WrappedTableExport] = {}
        self.fields: dict[int, tuple[ast.FieldType, str]] = {}
        self.properties: dict[int, tuple[ast.PropertyType, str, bool]] = {}
        self.reads_lazy_join = False
        self._names: dict[tuple[object, ...], str] = {}

    def visit_field(self, node: ast.Field) -> None:
        field_type = node.type
        while isinstance(field_type, ast.FieldAliasType):
            field_type = field_type.type
        if isinstance(field_type, ast.PropertyType):
            self._collect_property(field_type)
        elif isinstance(field_type, ast.FieldType):
            self._collect_field(field_type)

    def _collect_field(self, field_type: ast.FieldType) -> None:
        hops = _hops_to_table(field_type.table_type, self.table)
        if hops is None:
            return
        field_chain = (*(hop.field for hop in hops), field_type.name)
        name = self._export(("field", field_chain), field_chain, (), raw_property=False)
        self.fields[id(field_type)] = (field_type, name)
        self._note_hops(hops)

    def _collect_property(self, property_type: ast.PropertyType) -> None:
        document = property_type.field_type
        hops = _hops_to_table(document.table_type, self.table)
        if hops is None:
            return
        through_lazy_join = any(isinstance(hop, ast.LazyJoinType) for hop in hops)
        field_chain = (*(hop.field for hop in hops), document.name)
        property_path = tuple(property_type.chain)
        # An integer array index and a string key with the same text are different paths.
        key = ("property", field_chain, *((isinstance(link, int), link) for link in property_path))
        name = self._export(key, field_chain, property_path, raw_property=not through_lazy_join)
        self.properties[id(property_type)] = (property_type, name, through_lazy_join)
        self._note_hops(hops)

    def _note_hops(self, hops: list[ast.LazyJoinType | ast.VirtualTableType]) -> None:
        if any(isinstance(hop, ast.LazyJoinType) for hop in hops):
            self.reads_lazy_join = True

    def _export(
        self,
        key: tuple[object, ...],
        field_chain: tuple[str, ...],
        property_path: tuple[str | int, ...],
        raw_property: bool,
    ) -> str:
        name = self._names.get(key)
        if name is None:
            # Joining the path with the separator is not injective (`a.b` and `a___b` collide), so a taken name
            # gets a counter. Traversal order is fixed, which keeps the generated SQL stable.
            base = "___".join(str(link) for link in (*field_chain, *property_path))
            name = base
            counter = 1
            while name in self.exports:
                counter += 1
                name = f"{base}_{counter}"
            self._names[key] = name
            self.exports[name] = WrappedTableExport(
                name=name, field_chain=field_chain, property_path=property_path, raw_property=raw_property
            )
        return name


class LazyFinder(TraversingVisitor):
    found_lazy: bool = False
    max_type_visits: int = 1

    def __init__(self) -> None:
        self.visited_field_type_counts: dict[int, int] = {}

    def visit_lazy_join_type(self, node: ast.LazyJoinType):
        self.found_lazy = True

    def visit_lazy_table_type(self, node: ast.LazyTableType):
        self.found_lazy = True

    def visit_field_type(self, node: ast.FieldType):
        node_ref = id(node.table_type)
        visited_count = self.visited_field_type_counts.get(node_ref, 0)
        if visited_count < self.max_type_visits:
            self.visited_field_type_counts[node_ref] = visited_count + 1
            self.visit(node.table_type)


class LazyTableResolver(TraversingVisitor):
    lazy_finder_counter = 0

    def __init__(
        self,
        dialect: HogQLDialect,
        stack: Optional[list[ast.SelectQuery]],
        context: HogQLContext,
        resolver_factory: ResolverFactory | None = None,
    ):
        super().__init__()
        self.field_collectors: list[list[ast.FieldType | ast.PropertyType]] = [[]] if stack else []
        self.context = context
        self.dialect: HogQLDialect = dialect
        # forwarded to nested resolve_types/resolve_lazy_tables calls so a caller-supplied
        # factory (e.g. BoundedResolver) applies to subqueries built mid-transform
        self.resolver_factory = resolver_factory

    def _find_tables_needing_lazy_preresolution(
        self, node: ast.SelectQuery, select_type: ast.SelectQueryType
    ) -> list[str]:
        """Aliases of joined tables whose own ON constraint reads one of their lazy joins.

        A lazy join is added after the table it hangs off, so its columns are not yet in scope in that table's ON
        constraint. The table is wrapped in a subquery that performs the lazy join first.
        """
        tables_to_wrap: list[str] = []
        join_ptr = node.select_from
        while join_ptr:
            if join_ptr.constraint is not None and isinstance(join_ptr.table, ast.Field) and join_ptr.type is not None:
                for table_alias, table_type in select_type.tables.items():
                    if table_type is not join_ptr.type:
                        continue
                    collector = WrappedTableReferenceCollector(table_type)
                    collector.visit(join_ptr.constraint)
                    if collector.reads_lazy_join:
                        tables_to_wrap.append(table_alias)
                    break
            join_ptr = join_ptr.next_join
        return tables_to_wrap

    def _wrap_table_for_lazy_resolution(
        self, node: ast.SelectQuery, table_alias: str, select_type: ast.SelectQueryType
    ) -> None:
        # The scope key of a schema-qualified table (`posthog__events`) is not its written name, so match the binding.
        original_table_type = select_type.tables[table_alias]
        join_ptr = node.select_from
        while join_ptr is not None and join_ptr.type is not original_table_type:
            join_ptr = join_ptr.next_join
        assert join_ptr is not None and isinstance(join_ptr.table, ast.Field), f"Table {table_alias} not found"

        # Collect while the outer reads still identify the table they belong to.
        collector = WrappedTableReferenceCollector(original_table_type)
        collector.visit(node)

        subquery = ast.SelectQuery(
            select=[
                ast.Alias(alias=export.name, expr=ast.Field(chain=[table_alias, *export.field_chain]))
                for export in collector.exports.values()
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=list(join_ptr.table.chain)), alias=table_alias),
        )
        subquery = cast(
            ast.SelectQuery,
            resolve_types(subquery, self.context, self.dialect, [], resolver_factory=self.resolver_factory),
        )
        assert subquery.type is not None
        columns = [cast(ast.Alias, column) for column in subquery.select]
        for column in columns:
            export = collector.exports[column.alias]
            if export.property_path:
                self._read_property_path(subquery.type, column, export.property_path)
        resolve_lazy_tables(subquery, self.dialect, [subquery], self.context, resolver_factory=self.resolver_factory)
        for column in columns:
            if collector.exports[column.alias].raw_property:
                # The property-type pass runs after this and would convert a typed property inside the subquery.
                # The outer read must receive the stored value, because it may sit under an explicit string parser
                # (toFloatOrZero) that rejects the converted type, so the inner read is lowered to a raw extract now.
                column.expr = lower_property_access(column.expr, self.context)

        join_ptr.table = subquery
        join_ptr.alias = table_alias
        join_ptr.type = ast.SelectQueryAliasType(alias=table_alias, select_query_type=subquery.type)
        select_type.tables[table_alias] = join_ptr.type

        for property_type, export_name, through_lazy_join in collector.properties.values():
            if id(property_type.field_type) in collector.fields:
                # A key read through a select alias of the document (`properties AS p, p.amount`) shares the
                # document's field type, which is rebound below. The property keeps its own copy of the source.
                property_type.field_type = dataclasses.replace(property_type.field_type)
            # The field type keeps the original table so the property-type pass still finds the property's
            # definition, while the printer reads the exported column.
            property_type.joined_subquery = join_ptr.type
            property_type.joined_subquery_field_name = export_name
            if through_lazy_join:
                # The lazy join's subquery converted the value already, as it does without this wrapper.
                property_type.field_type.table_type = join_ptr.type
        for field_type, export_name in collector.fields.values():
            field_type.name = export_name
            field_type.table_type = join_ptr.type

    def _read_property_path(
        self, subquery_type: ast.SelectQueryType, column: ast.Alias, property_path: tuple[str | int, ...]
    ) -> None:
        """Turn the resolved document read in `column` into a read of `property_path` from that document.

        The resolver stringifies every chain link it resolves, so the path is applied through `get_child` afterwards,
        as array access resolution does, which keeps an integer index an integer.
        """
        document = column.expr
        while isinstance(document, ast.Alias):
            document = document.expr
        assert isinstance(document, ast.Field) and isinstance(document.type, ast.FieldType)
        read_type: ast.FieldType | ast.PropertyType = document.type
        for link in property_path:
            child = read_type.get_child(link, self.context)
            assert isinstance(child, ast.PropertyType)
            read_type = child
        column.expr = ast.Field(chain=[*document.chain, *property_path], type=read_type)
        column.type = ast.FieldAliasType(alias=column.alias, type=read_type)
        subquery_type.columns[column.alias] = column.type

    def visit_property_type(self, node: ast.PropertyType):
        if node.joined_subquery is not None:
            # we have already visited this property
            return

        table_type = node.field_type.table_type
        while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType, ast.VirtualTableType)):
            table_type = table_type.table_type

        if isinstance(table_type, ast.LazyJoinType) or isinstance(table_type, ast.LazyTableType):
            if self.context and self.context.within_non_hogql_query:
                # If we're in a non-HogQL query, traverse deeper, just like we normally would have.
                self.visit(node.field_type)
            else:
                # Place the property in a list for processing in "visit_select_query"
                if len(self.field_collectors) == 0:
                    raise ResolutionError("Can't access a lazy field when not in a SelectQuery context")
                self.field_collectors[-1].append(node)

    def visit_field_type(self, node: ast.FieldType):
        table_type: ast.TableOrSelectType | ast.TableAliasType = node.table_type
        while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType, ast.VirtualTableType)):
            table_type = table_type.table_type

        if isinstance(table_type, ast.LazyJoinType) or isinstance(table_type, ast.LazyTableType):
            # Each time we find a field, we place it in a list for processing in "visit_select_query"
            if len(self.field_collectors) == 0:
                raise ResolutionError("Can't access a lazy field when not in a SelectQuery context")
            self.field_collectors[-1].append(node)

    def visit_cte(self, node: ast.CTE):
        self.visit(node.expr)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        with self.context.entering_select(node.view_name):
            self._resolve_lazy_tables_in_select(node)

    def _resolve_lazy_tables_in_select(self, node: ast.SelectQuery) -> None:
        select_type = node.type
        if not select_type:
            raise ResolutionError("Select query must have a type")

        assert node.type is not None
        assert select_type is not None

        # Visit CTEs first to resolve any lazy joins inside them before processing the main query
        if node.ctes:
            for cte in node.ctes.values():
                self.visit_cte(cte)

        # Collect each `ast.Field` with `ast.LazyJoinType`
        field_collector: list[ast.FieldType | ast.PropertyType] = []
        self.field_collectors.append(field_collector)

        # Collect all visited fields on lazy tables into field_collector
        super().visit_select_query(node)

        # Collect all the joins we need to add to the select query
        joins_to_add: dict[str, LazyJoinToAdd] = {}
        tables_to_add: dict[str, LazyTableToAdd] = {}
        # Field types retain the original tables after the scope replaces them with subqueries.
        original_select_type = ast.SelectQueryType(tables=dict(select_type.tables))

        # First properties, then fields. This way we always get the smallest units to query first.
        matched_properties: list[ast.PropertyType | ast.FieldType] = [
            property for property in field_collector if isinstance(property, ast.PropertyType)
        ]
        matched_fields: list[ast.PropertyType | ast.FieldType] = [
            field for field in field_collector if isinstance(field, ast.FieldType)
        ]
        sorted_properties: list[ast.PropertyType | ast.FieldType] = matched_properties + matched_fields

        # Look for tables without requested fields to support cases like `select count() from table`
        join = node.select_from
        while join:
            if join.table is not None and isinstance(join.table.type, ast.LazyTableType):
                fields: list[ast.FieldType | ast.PropertyType] = []
                for field_or_property in field_collector:
                    if isinstance(field_or_property, ast.FieldType):
                        if isinstance(
                            field_or_property.table_type,
                            (ast.TableAliasType, ast.ColumnAliasedTableType, ast.VirtualTableType),
                        ):
                            if field_or_property.table_type.table_type == join.table.type:
                                fields.append(field_or_property)
                        else:
                            if field_or_property.table_type == join.table.type:
                                fields.append(field_or_property)
                    elif isinstance(field_or_property, ast.PropertyType):
                        if isinstance(
                            field_or_property.field_type.table_type,
                            (ast.TableAliasType, ast.ColumnAliasedTableType, ast.VirtualTableType),
                        ):
                            if field_or_property.field_type.table_type.table_type == join.table.type:
                                fields.append(field_or_property)
                        else:
                            if field_or_property.field_type.table_type == join.table.type:
                                fields.append(field_or_property)
                if len(fields) == 0:
                    table_name = join.alias or get_long_table_name(select_type, join.table.type)
                    tables_to_add[table_name] = LazyTableToAdd(fields_accessed={}, lazy_table=join.table.type.table)
            join = join.next_join

        for field_or_property in sorted_properties:
            if isinstance(field_or_property, ast.FieldType):
                property = None
                field = field_or_property
            elif isinstance(field_or_property, ast.PropertyType):
                property = field_or_property
                field = property.field_type
            else:
                raise ResolutionError("Should not be reachable")
            table_type = field.table_type

            # Traverse the lazy tables until we reach a real table, collecting them in a list.
            # Usually there's just one or two.
            table_types: list[
                ast.LazyJoinType
                | ast.LazyTableType
                | ast.TableAliasType
                | ast.ColumnAliasedTableType
                | ast.VirtualTableType
            ] = []
            while (
                isinstance(table_type, ast.TableAliasType)
                or isinstance(table_type, ast.ColumnAliasedTableType)
                or isinstance(table_type, ast.LazyJoinType)
                or isinstance(table_type, ast.LazyTableType)
                or isinstance(table_type, ast.VirtualTableType)
            ):
                if isinstance(table_type, ast.VirtualTableType):
                    table_type = table_type.table_type
                    continue
                if isinstance(table_type, ast.LazyJoinType):
                    table_types.append(table_type)
                    table_type = table_type.table_type
                    continue
                if isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
                    table_types.append(table_type)
                    table_type = table_type.table_type
                    break
                if isinstance(table_type, ast.LazyTableType):
                    table_types.append(table_type)
                    break

            # Loop over the collected lazy tables in reverse order to create the joins
            # TODO: the code below needs a good refactor... it's very repetitive
            for table_type in reversed(table_types):
                if isinstance(table_type, ast.LazyJoinType):
                    if isinstance(table_type.table_type, ast.VirtualTableType):
                        from_table = get_long_table_name(select_type, table_type.table_type.table_type)
                    else:
                        from_table = get_long_table_name(select_type, table_type.table_type)

                    to_table = get_long_table_name(select_type, table_type)
                    if to_table not in joins_to_add:
                        joins_to_add[to_table] = LazyJoinToAdd(
                            fields_accessed={},  # collect here all fields accessed on this table
                            lazy_join=table_type.lazy_join,
                            from_table=from_table,
                            to_table=to_table,
                            lazy_join_type=table_type,
                        )
                    new_join = joins_to_add[to_table]

                    if table_type == field.table_type or (
                        isinstance(field.table_type, ast.VirtualTableType) and table_type == field.table_type.table_type
                    ):
                        chain: list[str | int] = []
                        if isinstance(field.table_type, ast.VirtualTableType):
                            chain.append(field.table_type.field)
                        chain.append(field.name)
                        if property is not None:
                            chain.extend(property.chain)
                            property.joined_subquery_field_name = "___".join(str(x) for x in chain)
                            new_join.fields_accessed[property.joined_subquery_field_name] = chain
                        else:
                            new_join.fields_accessed[field.name] = chain
                elif isinstance(table_type, ast.LazyTableType):
                    table_name = get_long_table_name(select_type, table_type)
                    if table_name not in tables_to_add:
                        tables_to_add[table_name] = LazyTableToAdd(
                            fields_accessed={},  # collect here all fields accessed on this table
                            lazy_table=table_type.table,
                        )
                    new_table = tables_to_add[table_name]
                    if table_type == field.table_type or (
                        isinstance(field.table_type, ast.VirtualTableType) and table_type == field.table_type.table_type
                    ):
                        lazy_chain: list[str | int] = []
                        if isinstance(field.table_type, ast.VirtualTableType):
                            lazy_chain.append(field.table_type.field)
                        lazy_chain.append(field.name)
                        if property is not None:
                            lazy_chain.extend(property.chain)
                            property.joined_subquery_field_name = "___".join(str(x) for x in lazy_chain)
                            new_table.fields_accessed[property.joined_subquery_field_name] = lazy_chain
                        else:
                            new_table.fields_accessed[field.name] = lazy_chain
                elif isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
                    # Widen mypy's view of the inner type: the annotated union is
                    # `TableType | LazyTableType`, but the LazyJoinType branch below is a
                    # defensive runtime guard against annotation drift.
                    inner_table_type = cast(
                        "ast.TableType | ast.LazyTableType | ast.LazyJoinType",
                        table_type.table_type,
                    )
                    if isinstance(inner_table_type, ast.LazyJoinType):
                        from_table = get_long_table_name(select_type, inner_table_type)
                        to_table = get_long_table_name(select_type, table_type)
                        if to_table not in joins_to_add:
                            joins_to_add[to_table] = LazyJoinToAdd(
                                fields_accessed={},  # collect here all fields accessed on this table
                                lazy_join=inner_table_type.lazy_join,
                                from_table=from_table,
                                to_table=to_table,
                                lazy_join_type=inner_table_type,
                            )
                        new_join = joins_to_add[to_table]
                        if table_type == field.table_type or (
                            isinstance(field.table_type, ast.VirtualTableType)
                            and table_type == field.table_type.table_type
                        ):
                            field_chain: list[str | int] = []
                            if isinstance(field.table_type, ast.VirtualTableType):
                                field_chain.append(field.table_type.field)
                            field_chain.append(field.name)
                            if property is not None:
                                field_chain.extend(property.chain)
                                property.joined_subquery_field_name = "___".join(str(x) for x in field_chain)
                                new_join.fields_accessed[property.joined_subquery_field_name] = field_chain
                            else:
                                new_join.fields_accessed[field.name] = field_chain
                    elif isinstance(inner_table_type, ast.LazyTableType):
                        table_name = get_long_table_name(select_type, table_type)
                        if table_name not in tables_to_add:
                            tables_to_add[table_name] = LazyTableToAdd(
                                fields_accessed={},  # collect here all fields accessed on this table
                                lazy_table=cast(ast.LazyTable, inner_table_type.table),
                            )
                        new_table = tables_to_add[table_name]
                        if table_type == field.table_type or (
                            isinstance(field.table_type, ast.VirtualTableType)
                            and table_type == field.table_type.table_type
                        ):
                            chain = []
                            if isinstance(field.table_type, ast.VirtualTableType):
                                chain.append(field.table_type.field)
                            chain.append(field.name)
                            if property is not None:
                                chain.extend(property.chain)
                                property.joined_subquery_field_name = "___".join(str(x) for x in chain)
                                new_table.fields_accessed[property.joined_subquery_field_name] = chain
                            else:
                                new_table.fields_accessed[field.name] = chain

        # Make sure we also add fields we will use for the join's "ON" condition into the list of fields accessed.
        # Without this "pdi.person.id" won't work if you did not ALSO select "pdi.person_id" explicitly for the join.
        join_constraint_overrides: dict[str, list[ConstraintOverride]] = {}

        def create_override(table_name: str, field_chain: list[str | int]) -> None:
            alias = f"{table_name}___{'___'.join(str(x) for x in field_chain)}"

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
                for extra_from_field in new_join.lazy_join.extra_from_fields:
                    create_override(new_join.from_table, extra_from_field)
            if new_join.lazy_join.to_field is not None and (
                new_join.to_table in joins_to_add or new_join.to_table in tables_to_add
            ):
                create_override(new_join.to_table, new_join.lazy_join.to_field)

        # Pre-wrap tables whose JOIN constraints reference their own lazy joins.
        # This must happen BEFORE we add lazy joins to avoid forward reference issues.
        tables_to_wrap = self._find_tables_needing_lazy_preresolution(node, select_type)
        wrapped_table_types = [select_type.tables[table_alias] for table_alias in tables_to_wrap]
        for table_alias in tables_to_wrap:
            self._wrap_table_for_lazy_resolution(node, table_alias, select_type)

        # Remove lazy joins that are now resolved inside wrapped subqueries
        joins_to_add = {
            k: v
            for k, v in joins_to_add.items()
            if not any(_hops_to_table(v.lazy_join_type, wrapped) is not None for wrapped in wrapped_table_types)
        }

        # For all the collected tables, create the subqueries, and add them to the table.
        for table_name, table_to_add in tables_to_add.items():
            subquery = table_to_add.lazy_table.lazy_select(table_to_add, self.context, node=node)
            subquery = cast(ast.SelectQuery, clone_expr(subquery, clear_locations=True))
            subquery = cast(
                ast.SelectQuery,
                resolve_types(
                    subquery, self.context, self.dialect, [select_type], resolver_factory=self.resolver_factory
                ),
            )
            if self.context.property_swapper is not None:
                subquery = PropertySwapper(
                    timezone=self.context.property_swapper.timezone,
                    group_properties=self.context.property_swapper.group_properties,
                    event_properties={},
                    person_properties={},
                    context=self.context,
                    setTimeZones=False,
                ).visit(subquery)
            old_table_type = select_type.tables[table_name]
            select_type.tables[table_name] = ast.SelectQueryAliasType(alias=table_name, select_query_type=subquery.type)

            join_ptr = node.select_from
            while join_ptr:
                if join_ptr.table is not None and (
                    join_ptr.table.type == old_table_type
                    or (
                        isinstance(old_table_type, (ast.TableAliasType, ast.ColumnAliasedTableType))
                        and join_ptr.table.type == old_table_type.table_type
                    )
                ):
                    join_ptr.table = subquery
                    join_ptr.type = select_type.tables[table_name]
                    join_ptr.alias = table_name
                    # A lazy table expands into an aggregating subquery. ClickHouse rejects a SAMPLE
                    # modifier on a subquery, and sampling a pre-aggregated table is meaningless, so
                    # drop the modifier rather than emitting invalid SQL.
                    if join_ptr.sample is not None:
                        self.context.add_warning(
                            f'SAMPLE clause ignored: the "{table_name}" table is computed on the fly and cannot be sampled',
                            start=join_ptr.sample.start,
                            end=join_ptr.sample.end,
                        )
                        join_ptr.sample = None
                    break
                join_ptr = join_ptr.next_join

        # For all the collected joins, create the join subqueries, and add them to the table.
        for to_table, join_scope in joins_to_add.items():
            join_to_add: ast.JoinExpr = join_scope.lazy_join.resolve_join_to_add(
                join_scope,
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
            join_to_add = cast(
                ast.JoinExpr,
                resolve_types(
                    join_to_add, self.context, self.dialect, [select_type], resolver_factory=self.resolver_factory
                ),
            )
            if self.context.property_swapper is not None:
                join_to_add = PropertySwapper(
                    timezone=self.context.property_swapper.timezone,
                    group_properties=self.context.property_swapper.group_properties,
                    event_properties={},
                    person_properties={},
                    context=self.context,
                    setTimeZones=False,
                ).visit(join_to_add)

            if join_to_add.type is not None:
                select_type.tables[to_table] = join_to_add.type

            constraint_field_chains = find_field_chains(join_to_add.constraint)

            select_from_alias: str | int | None = None
            if node.select_from and node.select_from.alias:
                select_from_alias = node.select_from.alias
            else:
                if node.select_from and node.select_from.table and isinstance(node.select_from.table, ast.Field):
                    select_from_alias = node.select_from.table.chain[0]

            # Store all the constraint tables we've seen for this join to decide where in the order of joins the next join should be added
            constraint_tables: list[str | int] = []
            for field_chain in constraint_field_chains:
                if field_chain[0] == select_from_alias:
                    continue

                added = False
                for constraint_table_join in joins_to_add.values():
                    if field_chain[0] == constraint_table_join.lazy_join_type.field:
                        constraint_tables.append(constraint_table_join.to_table)
                        added = True
                        break

                if not added:
                    constraint_tables.append(field_chain[0])

            join_ptr = node.select_from
            added = False
            while join_ptr:
                if join_scope.from_table == join_ptr.alias or (
                    isinstance(join_ptr.table, ast.Field) and join_scope.from_table == join_ptr.table.chain[0]
                ):
                    # The join's ON constraint may depend on other joins (`constraint_tables`); the
                    # ones that matter here are those earlier in this source table's join chain,
                    # which ClickHouse resolves left-to-right and so must appear before this join.
                    # Scan the whole remaining chain — not just the immediate next join — and insert
                    # after the last such dependency, or right after the source table when none are
                    # present. Looking only one join ahead placed this join before a dependency that
                    # a non-dependent join had been inserted in front of.
                    insert_after = join_ptr
                    scan = join_ptr.next_join
                    while scan is not None:
                        if scan.alias in constraint_tables:
                            insert_after = scan
                        scan = scan.next_join
                    join_to_add.next_join = insert_after.next_join
                    insert_after.next_join = join_to_add
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

            # Collect any fields or properties that may have been added by the join resolver with the LazyJoinType
            join_field_collector: list[ast.FieldType | ast.PropertyType] = []
            self.field_collectors.append(join_field_collector)
            super().visit(join_to_add)
            self.field_collectors.pop()
            field_collector.extend(join_field_collector)

        # Assign all types on the fields we collected earlier
        for field_or_property in field_collector:
            if isinstance(field_or_property, ast.FieldType):
                table_type = field_or_property.table_type
            elif isinstance(field_or_property, ast.PropertyType):
                table_type = field_or_property.field_type.table_type
            else:
                raise ResolutionError("Should not be reachable")

            while isinstance(table_type, ast.VirtualTableType):
                table_type = table_type.table_type

            table_name = get_long_table_name(original_select_type, table_type)
            try:
                table_type = select_type.tables[table_name]
            except KeyError:
                # If the table is not found, then it's likely that it'll need to be resolved on a second pass of lazy_tables
                continue

            if isinstance(field_or_property, ast.FieldType):
                field_or_property.table_type = table_type
            elif isinstance(field_or_property, ast.PropertyType):
                field_or_property.field_type.table_type = table_type
                field_or_property.joined_subquery = cast(ast.SelectQueryAliasType, table_type)

        self.field_collectors.pop()

        # When joining a lazy table to another lazy table, the joined table doesn't get resolved
        # Doing another pass solves this for us
        if self.lazy_finder_counter < 20:
            lazy_finder = LazyFinder()
            lazy_finder.visit(node)
            if lazy_finder.found_lazy:
                self.lazy_finder_counter = self.lazy_finder_counter + 1
                self.visit_select_query(node)
