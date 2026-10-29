from datetime import UTC, datetime
from functools import partial

from posthog.hogql import ast
from posthog.hogql.constants import FLAG_CALLED_EVENT
from posthog.hogql.database.models import (
    DatabaseField,
    ExpressionField,
    FieldOrTable,
    LazyJoin,
    LazyTable,
    LazyTableToAdd,
    StringJSONDatabaseField,
    Table,
    VirtualTable,
)
from posthog.hogql.database.schema.events import EVENTS_AVOID_ASTERISK_FIELDS, EventsTable
from posthog.hogql.database.schema.flag_evaluations import FlagEvaluationsTable, flag_evaluations_coverage_start
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import GetFieldsTraverser

EVENTS_WITH_FLAG_CALLS_TABLE = "events_with_flag_calls"
EVENTS_WITH_FLAG_CALLS_CHAIN: list[str] = ["posthog", EVENTS_WITH_FLAG_CALLS_TABLE]

# Ingestion writes a flag call to flag_evaluations only when `$feature_flag` is a non-empty JSON string. The raw JSON
# text of a string value starts with a quote, and a number, boolean or object does not. On the native JSON events
# table the printer converts a typed key before this test reads it, so mode 1 queries there keep reading events. The
# test reads only the raw JSON text, because a materialized `$feature_flag` column reads an empty string as missing.
_HAS_FLAG_KEY = (
    "startsWith(JSONExtractRaw(events.properties, '$feature_flag'), '\"') "
    "AND JSONExtractRaw(events.properties, '$feature_flag') != '\"\"'"
)


def _field(table: Table, chain: list[str | int]) -> tuple[FieldOrTable | None, list[str | int]]:
    """The field that `chain` names on `table`, through a virtual table, and the rest of the chain below it."""
    field = table.fields.get(str(chain[0]))
    if isinstance(field, VirtualTable) and len(chain) > 1:
        return field.fields.get(str(chain[1])), chain[2:]
    return field, chain[1:]


def _column_name(field: FieldOrTable | None) -> str | None:
    # An ExpressionField is a DatabaseField too, but it names no column.
    if isinstance(field, DatabaseField) and not isinstance(field, ExpressionField):
        return field.name
    return None


def _is_expression(table: Table, chain: list[str | int]) -> bool:
    return isinstance(_field(table, chain)[0], ExpressionField)


def property_read(table: Table, chain: list[str | int]) -> tuple[str, str] | None:
    """The stored JSON column and the top-level key that `chain` reads on `table`, or None when it reads no property."""
    field, rest = _field(table, chain)
    column = _column_name(field)
    if not isinstance(field, StringJSONDatabaseField) or column is None or not rest:
        return None
    return column, str(rest[0])


def column_chains(table: Table, chain: list[str | int]) -> list[list[str | int]]:
    """The chains of stored columns that `chain` reads on `table`, through the expression fields and the keys of the
    joins that it reads."""
    field, _ = _field(table, chain)
    if not isinstance(field, ExpressionField):
        return [chain]
    chains: list[list[str | int]] = []
    for read in GetFieldsTraverser(field.expr).fields:
        joined = table.fields.get(str(read.chain[0]))
        if isinstance(joined, LazyJoin) and len(read.chain) > 1:
            chains.extend(column_chains(table, list(joined.from_field)))
        else:
            chains.extend(column_chains(table, list(read.chain)))
    return chains


class FlagEvaluationsColumns:
    """Maps a chain on the events fields to the chain on `posthog.flag_evaluations` that holds the same value."""

    def __init__(self, events: Table, flag_evaluations: Table) -> None:
        self.events = events
        self.flag_evaluations = flag_evaluations
        self._chains_by_column: dict[str, list[str | int]] = {}
        for name, field in flag_evaluations.fields.items():
            if (column := _column_name(field)) is not None:
                self._chains_by_column.setdefault(column, [name])
        for name, field in flag_evaluations.fields.items():
            if isinstance(field, VirtualTable):
                for inner_name, inner in field.fields.items():
                    if (column := _column_name(inner)) is not None:
                        self._chains_by_column.setdefault(column, [name, inner_name])

    def chain(self, chain: list[str | int]) -> list[str | int] | None:
        """The chain on `flag_evaluations` that holds what `chain` reads on `events`, or None when it has none.

        A chain that reads an events column maps to the `flag_evaluations` field on the same column, such as
        `person_id` for `event_person_id`. Otherwise it maps to the `flag_evaluations` field of the same name, which
        that table defines for events names whose columns differ, such as `$session_id`. An expression field maps when
        each column it reads does.
        """
        field, rest = _field(self.events, chain)
        if isinstance(field, ExpressionField):
            reads = column_chains(self.events, chain)
            return chain if all(self.chain(read) is not None for read in reads) else None
        column = _column_name(field)
        if column is not None and column in self._chains_by_column:
            return [*self._chains_by_column[column], *rest]
        same_name = self.flag_evaluations.fields.get(str(chain[0]))
        if isinstance(same_name, VirtualTable):
            return chain if len(chain) > 1 and str(chain[1]) in same_name.fields else None
        return chain if same_name is not None else None


class EventsWithFlagCallsTable(LazyTable):
    """`events` with its flag calls since the coverage start read from `posthog.flag_evaluations` instead.

    Its `fields` is the events table's own dict, so every name binds as it does on `events`.
    """

    fields: dict[str, FieldOrTable] = {}

    def avoid_asterisk_fields(self) -> list[str]:
        return list(EVENTS_AVOID_ASTERISK_FIELDS)

    def lazy_select(self, table_to_add: LazyTableToAdd, context, node):
        # Deferred: the transforms import this table.
        from posthog.hogql.transforms.flag_calls_from_flag_evaluations import (  # noqa: PLC0415
            and_conditions,
            flag_key_typed_as_string,
        )
        from posthog.hogql.transforms.flag_calls_union import union_branch_filters, union_events_filter  # noqa: PLC0415

        assert context.database is not None
        # `SELECT count()` reads no field, and a subquery needs at least one column.
        accessed = dict(table_to_add.fields_accessed) or {"timestamp": ["timestamp"]}
        events_columns: list[ast.Expr] = [
            ast.Alias(alias=name, expr=ast.Field(chain=["events", *chain])) for name, chain in accessed.items()
        ]
        if any(_is_expression(self, chain) for chain in accessed.values()):
            # An expression field reaches here as the key of a join, such as `person_id` for `person`. Resolving it on
            # a second scan of this table puts its own joins, such as `override`, above the branches, so each runs
            # once. The second scan asks only for columns, and it reads the same filter from this query's WHERE.
            return ast.SelectQuery(
                select=events_columns,
                select_from=ast.JoinExpr(table=ast.Field(chain=list(EVENTS_WITH_FLAG_CALLS_CHAIN)), alias="events"),
                where=union_events_filter(node, self),
            )

        columns = FlagEvaluationsColumns(self, context.database.get_table(["posthog", "flag_evaluations"]))
        only_in_flag_evaluations = context.database.flag_calls_only_in_flag_evaluations
        cutoff = ast.Constant(value=flag_evaluations_coverage_start(datetime.now(UTC)))
        # Property type resolution ran before lazy tables, so the metadata holds the type of each property this query
        # reads, `$feature_flag` among them.
        filters = union_branch_filters(
            node, self, columns, partial(flag_key_typed_as_string, context.property_metadata)
        )

        def flag_evaluations_field(chain: list[str | int]) -> ast.Field:
            flag_chain = columns.chain(chain)
            if flag_chain is None:
                # union_unreadable_reason refuses such a query before lazy tables resolve.
                raise QueryError(f"posthog.flag_evaluations has no column for {'.'.join(str(part) for part in chain)}")
            return ast.Field(chain=["flag_evaluations", *flag_chain])

        def events_branch(*conditions: ast.Expr | None) -> ast.SelectQuery:
            return ast.SelectQuery(
                select=events_columns,
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                where=and_conditions([*conditions, filters.events]),
            )

        flag_call = parse_expr("events.event = {event}", {"event": ast.Constant(value=FLAG_CALLED_EVENT)})
        flag_call_since_cutoff = ast.And(
            exprs=[flag_call, parse_expr("events.timestamp >= {cutoff}", {"cutoff": cutoff})]
        )
        # On mode 2 every flag call comes from flag_evaluations, as the flag_evaluations swap reads it. That leaves out
        # the calls without a key, which ingestion keeps writing to events.
        moved = flag_call if only_in_flag_evaluations else flag_call_since_cutoff
        branches = [events_branch(ast.Not(expr=moved))]
        if not only_in_flag_evaluations and filters.keyless_flag_calls_can_match:
            branches.append(events_branch(flag_call_since_cutoff, ast.Not(expr=parse_expr(_HAS_FLAG_KEY))))
        branches.append(
            ast.SelectQuery(
                select=[ast.Alias(alias=name, expr=flag_evaluations_field(chain)) for name, chain in accessed.items()],
                select_from=ast.JoinExpr(
                    table=ast.Field(chain=["posthog", "flag_evaluations"]), alias="flag_evaluations"
                ),
                where=and_conditions(
                    [parse_expr("flag_evaluations.timestamp >= {cutoff}", {"cutoff": cutoff}), filters.flag_evaluations]
                ),
            )
        )
        return ast.SelectQuery(
            select=[ast.Field(chain=[name]) for name in accessed],
            select_from=ast.JoinExpr(table=ast.SelectSetQuery.create_from_queries(branches, "UNION ALL")),
        )

    def to_printed_clickhouse(self, context):
        return "events"

    def to_printed_hogql(self):
        return EVENTS_WITH_FLAG_CALLS_TABLE


def union_table_of(table_type: ast.Type | None) -> "EventsWithFlagCallsTable | None":
    """The union that `table_type` scans, through aliases and virtual tables, or None when it scans another table."""
    while isinstance(table_type, (ast.TableAliasType, ast.VirtualTableType)):
        table_type = table_type.table_type
    if isinstance(table_type, ast.LazyTableType) and isinstance(table_type.table, EventsWithFlagCallsTable):
        return table_type.table
    return None


# Tables whose rows are events with the events columns. Property types, access control and time bounds treat their reads
# as reads of events.
EVENT_ROW_TABLES = (EventsTable, FlagEvaluationsTable, EventsWithFlagCallsTable)
