from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DatabaseField,
    DateTimeDatabaseField,
    ExpressionField,
    FieldOrTable,
    FieldTraverser,
    IntegerDatabaseField,
    LazyJoin,
    LazyJoinToAdd,
    StringArrayDatabaseField,
    StringDatabaseField,
    Table,
    VirtualTable,
)
from posthog.hogql.database.schema.event_sessions import EventsSessionSubTable
from posthog.hogql.parser import parse_expr

if TYPE_CHECKING:
    pass


def add_hidden_soe_fields_to_events_table(events_table: Table) -> None:
    """
    Add hidden soe_* fields to the events table.

    These fields map directly to ClickHouse columns and are marked as hidden
    so they don't appear in autocomplete or SELECT *, but can be referenced
    by ExpressionFields in the session_on_events virtual table.
    """
    # Timestamps
    events_table.fields["soe_min_timestamp"] = DateTimeDatabaseField(name="soe_min_timestamp", hidden=True)
    events_table.fields["soe_max_timestamp"] = DateTimeDatabaseField(name="soe_max_timestamp", hidden=True)
    events_table.fields["soe_pageview_prio_timestamp_min"] = DateTimeDatabaseField(
        name="soe_pageview_prio_timestamp_min", hidden=True
    )
    events_table.fields["soe_pageview_prio_timestamp_max"] = DateTimeDatabaseField(
        name="soe_pageview_prio_timestamp_max", hidden=True
    )

    # URLs
    events_table.fields["soe_entry_url"] = StringDatabaseField(name="soe_entry_url", hidden=True)
    events_table.fields["soe_end_url"] = StringDatabaseField(name="soe_end_url", hidden=True)
    events_table.fields["soe_last_external_click_url"] = StringDatabaseField(
        name="soe_last_external_click_url", hidden=True
    )

    # Attribution
    events_table.fields["soe_entry_referring_domain"] = StringDatabaseField(
        name="soe_entry_referring_domain", hidden=True
    )
    events_table.fields["soe_entry_utm_source"] = StringDatabaseField(name="soe_entry_utm_source", hidden=True)
    events_table.fields["soe_entry_utm_campaign"] = StringDatabaseField(name="soe_entry_utm_campaign", hidden=True)
    events_table.fields["soe_entry_utm_medium"] = StringDatabaseField(name="soe_entry_utm_medium", hidden=True)
    events_table.fields["soe_entry_utm_term"] = StringDatabaseField(name="soe_entry_utm_term", hidden=True)
    events_table.fields["soe_entry_utm_content"] = StringDatabaseField(name="soe_entry_utm_content", hidden=True)
    events_table.fields["soe_entry_gclid"] = StringDatabaseField(name="soe_entry_gclid", hidden=True)
    events_table.fields["soe_entry_gad_source"] = StringDatabaseField(name="soe_entry_gad_source", hidden=True)
    events_table.fields["soe_entry_fbclid"] = StringDatabaseField(name="soe_entry_fbclid", hidden=True)

    # Boolean flags
    events_table.fields["soe_entry_has_gclid"] = BooleanDatabaseField(name="soe_entry_has_gclid", hidden=True)
    events_table.fields["soe_entry_has_fbclid"] = BooleanDatabaseField(name="soe_entry_has_fbclid", hidden=True)
    events_table.fields["soe_has_autocapture"] = BooleanDatabaseField(name="soe_has_autocapture", hidden=True)
    events_table.fields["soe_has_replay"] = BooleanDatabaseField(name="soe_has_replay", hidden=True)

    # Ad IDs - map and set
    events_table.fields["soe_entry_ad_ids_map"] = DatabaseField(name="soe_entry_ad_ids_map", hidden=True)
    events_table.fields["soe_entry_ad_ids_set"] = StringArrayDatabaseField(name="soe_entry_ad_ids_set", hidden=True)

    # Bounce rate calculation fields
    events_table.fields["soe_page_screen_uniq_up_to"] = DatabaseField(name="soe_page_screen_uniq_up_to", hidden=True)


def add_session_properties_to_session_sub_table(session_sub_table: VirtualTable) -> None:
    """
    Add session properties to the EventsSessionSubTable.

    These properties map to soe_* columns on the events table. This function should
    only be called when sessions on events mode is enabled.
    """
    # Timestamps
    session_sub_table.fields["$start_timestamp"] = StringDatabaseField(name="soe_min_timestamp")
    session_sub_table.fields["$end_timestamp"] = StringDatabaseField(name="soe_max_timestamp")
    # URLs
    session_sub_table.fields["$entry_current_url"] = StringDatabaseField(name="soe_entry_url")
    session_sub_table.fields["$end_current_url"] = StringDatabaseField(name="soe_end_url")
    session_sub_table.fields["$last_external_click_url"] = StringDatabaseField(name="soe_last_external_click_url")
    # Attribution
    session_sub_table.fields["$entry_referring_domain"] = StringDatabaseField(name="soe_entry_referring_domain")
    session_sub_table.fields["$entry_utm_source"] = StringDatabaseField(name="soe_entry_utm_source")
    session_sub_table.fields["$entry_utm_campaign"] = StringDatabaseField(name="soe_entry_utm_campaign")
    session_sub_table.fields["$entry_utm_medium"] = StringDatabaseField(name="soe_entry_utm_medium")
    session_sub_table.fields["$entry_utm_term"] = StringDatabaseField(name="soe_entry_utm_term")
    session_sub_table.fields["$entry_utm_content"] = StringDatabaseField(name="soe_entry_utm_content")
    session_sub_table.fields["$entry_gclid"] = StringDatabaseField(name="soe_entry_gclid")
    session_sub_table.fields["$entry_gad_source"] = StringDatabaseField(name="soe_entry_gad_source")
    session_sub_table.fields["$entry_fbclid"] = StringDatabaseField(name="soe_entry_fbclid")
    # Boolean flags
    session_sub_table.fields["$entry_has_gclid"] = StringDatabaseField(name="soe_entry_has_gclid")
    session_sub_table.fields["$entry_has_fbclid"] = StringDatabaseField(name="soe_entry_has_fbclid")
    session_sub_table.fields["$has_autocapture"] = StringDatabaseField(name="soe_has_autocapture")
    session_sub_table.fields["$has_replay"] = StringDatabaseField(name="soe_has_replay")
    # Ad IDs - map and set
    session_sub_table.fields["$entry_ad_ids_map"] = StringDatabaseField(name="soe_entry_ad_ids_map")
    session_sub_table.fields["$entry_ad_ids_set"] = StringDatabaseField(name="soe_entry_ad_ids_set")
    # Bounce rate calculation fields
    session_sub_table.fields["$page_screen_uniq_up_to"] = StringDatabaseField(name="soe_page_screen_uniq_up_to")


RAW_SESSIONS_OVERRIDES_FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id"),
    "session_id_v7": DatabaseField(name="session_id_v7"),
    "session_timestamp": DatabaseField(name="session_timestamp"),
    # Timestamps - SimpleAggregateFunction
    "min_timestamp": DateTimeDatabaseField(name="min_timestamp"),
    "max_timestamp": DateTimeDatabaseField(name="max_timestamp"),
    "pageview_prio_timestamp_min": DateTimeDatabaseField(name="pageview_prio_timestamp_min"),
    "pageview_prio_timestamp_max": DateTimeDatabaseField(name="pageview_prio_timestamp_max"),
    "max_inserted_at": DateTimeDatabaseField(name="max_inserted_at"),
    # URLs - AggregateFunction(argMin/argMax, ...)
    "has_pageview_or_screen": BooleanDatabaseField(name="has_pageview_or_screen"),
    "entry_url": DatabaseField(name="entry_url"),
    "end_url": DatabaseField(name="end_url"),
    "last_external_click_url": DatabaseField(name="last_external_click_url"),
    # Attribution - AggregateFunction(argMin, ...)
    "entry_referring_domain": DatabaseField(name="entry_referring_domain"),
    "entry_utm_source": DatabaseField(name="entry_utm_source"),
    "entry_utm_campaign": DatabaseField(name="entry_utm_campaign"),
    "entry_utm_medium": DatabaseField(name="entry_utm_medium"),
    "entry_utm_term": DatabaseField(name="entry_utm_term"),
    "entry_utm_content": DatabaseField(name="entry_utm_content"),
    "entry_gclid": DatabaseField(name="entry_gclid"),
    "entry_gad_source": DatabaseField(name="entry_gad_source"),
    "entry_fbclid": DatabaseField(name="entry_fbclid"),
    # Boolean flags
    "entry_has_gclid": BooleanDatabaseField(name="entry_has_gclid"),
    "entry_has_fbclid": BooleanDatabaseField(name="entry_has_fbclid"),
    # Ad IDs
    "entry_ad_ids_map": DatabaseField(name="entry_ad_ids_map"),
    "entry_ad_ids_set": StringArrayDatabaseField(name="entry_ad_ids_set"),
    # Bounce rate
    "page_screen_uniq_up_to": DatabaseField(name="page_screen_uniq_up_to"),
    "has_autocapture": BooleanDatabaseField(name="has_autocapture"),
    # Replay
    "has_replay": BooleanDatabaseField(name="has_replay"),
}


class SessionsOnEventsOverridesTable(Table):
    fields: dict[str, FieldOrTable] = RAW_SESSIONS_OVERRIDES_FIELDS

    def to_printed_clickhouse(self, context):
        return "raw_sessions_overrides_v3"

    def to_printed_hogql(self):
        return "raw_sessions_overrides_v3"

    def avoid_asterisk_fields(self) -> list[str]:
        return [
            "entry_url",
            "end_url",
            "last_external_click_url",
            "entry_referring_domain",
            "entry_utm_source",
            "entry_utm_campaign",
            "entry_utm_medium",
            "entry_utm_term",
            "entry_utm_content",
            "entry_gclid",
            "entry_gad_source",
            "entry_fbclid",
            "entry_ad_ids_map",
            "page_screen_uniq_up_to",
        ]


def join_with_sessions_on_events_overrides(
    join_to_add: LazyJoinToAdd,
    context: HogQLContext,
    node: ast.SelectQuery,
) -> ast.JoinExpr:
    """
    Join events table to session overrides table.

    The overrides table contains AggregateFunction states, so we need to use merge functions
    to read them. This generates a subquery that:
    1. Groups by session_id_v7
    2. Uses argMinMerge/argMaxMerge for aggregate function states
    3. Only selects fields that are accessed in the query
    """

    table_name = "raw_sessions_overrides_v3"

    def arg_min_merge(field_name: str) -> ast.Call:
        return ast.Call(name="argMinMerge", args=[ast.Field(chain=[table_name, field_name])])

    def arg_max_merge(field_name: str) -> ast.Call:
        return ast.Call(name="argMaxMerge", args=[ast.Field(chain=[table_name, field_name])])

    merge_fields: dict[str, ast.Expr] = {
        "min_timestamp": ast.Call(name="min", args=[ast.Field(chain=[table_name, "min_timestamp"])]),
        "max_timestamp": ast.Call(name="max", args=[ast.Field(chain=[table_name, "max_timestamp"])]),
        "pageview_prio_timestamp_min": ast.Call(
            name="min", args=[ast.Field(chain=[table_name, "pageview_prio_timestamp_min"])]
        ),
        "pageview_prio_timestamp_max": ast.Call(
            name="max", args=[ast.Field(chain=[table_name, "pageview_prio_timestamp_max"])]
        ),
        "max_inserted_at": ast.Call(name="max", args=[ast.Field(chain=[table_name, "max_inserted_at"])]),
        "has_pageview_or_screen": ast.Call(name="max", args=[ast.Field(chain=[table_name, "has_pageview_or_screen"])]),
        "entry_url": arg_min_merge("entry_url"),
        "end_url": arg_max_merge("end_url"),
        "last_external_click_url": arg_max_merge("last_external_click_url"),
        "entry_referring_domain": arg_min_merge("entry_referring_domain"),
        "entry_utm_source": arg_min_merge("entry_utm_source"),
        "entry_utm_campaign": arg_min_merge("entry_utm_campaign"),
        "entry_utm_medium": arg_min_merge("entry_utm_medium"),
        "entry_utm_term": arg_min_merge("entry_utm_term"),
        "entry_utm_content": arg_min_merge("entry_utm_content"),
        "entry_gclid": arg_min_merge("entry_gclid"),
        "entry_gad_source": arg_min_merge("entry_gad_source"),
        "entry_fbclid": arg_min_merge("entry_fbclid"),
        "entry_has_gclid": arg_min_merge("entry_has_gclid"),
        "entry_has_fbclid": arg_min_merge("entry_has_fbclid"),
        "entry_ad_ids_map": arg_min_merge("entry_ad_ids_map"),
        "entry_ad_ids_set": arg_min_merge("entry_ad_ids_set"),
        "page_screen_uniq_up_to": ast.Call(
            name="groupUniqArrayMerge",
            params=[ast.Constant(value=2)],
            args=[ast.Field(chain=[table_name, "page_screen_uniq_up_to"])],
        ),
        "has_autocapture": ast.Call(name="max", args=[ast.Field(chain=[table_name, "has_autocapture"])]),
        "has_replay": ast.Call(name="max", args=[ast.Field(chain=[table_name, "has_replay"])]),
    }

    select_fields: list[ast.Expr] = []
    for field_name in join_to_add.fields_accessed.keys():
        if field_name in merge_fields:
            select_fields.append(ast.Alias(alias=field_name, expr=merge_fields[field_name]))
        elif field_name == "session_id_v7":
            select_fields.append(ast.Field(chain=[table_name, "session_id_v7"]))
        else:
            select_fields.append(ast.Alias(alias=field_name, expr=ast.Field(chain=[table_name, field_name])))

    if "session_id_v7" not in join_to_add.fields_accessed:
        select_fields.append(ast.Field(chain=[table_name, "session_id_v7"]))

    subquery = ast.SelectQuery(
        select=select_fields,
        select_from=ast.JoinExpr(table=ast.Field(chain=[table_name])),
        group_by=[ast.Field(chain=[table_name, "session_id_v7"])],
    )

    join_expr = ast.JoinExpr(table=subquery)
    join_expr.join_type = "LEFT JOIN"
    join_expr.alias = join_to_add.to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[join_to_add.from_table, "$session_id_uuid"]),
            right=ast.Field(chain=[join_to_add.to_table, "session_id_v7"]),
        ),
        constraint_type="ON",
    )

    return join_expr


def use_session_properties_from_events_with_overrides(events_table: Table) -> None:
    """
    Configure events.session to use soe_* columns with overrides from raw_sessions_overrides_v3.

    Pattern:
    1. Add hidden soe_* fields to events table (so ExpressionFields can reference them)
    2. events.session_on_events → EventsSessionSubTable (virtual table mapping to soe_* columns)
    3. events.session_overrides → LazyJoin to overrides table (only added if session properties accessed)
    4. events.session → FieldTraverser to session_on_events
    5. For each session property: Replace with ExpressionField using if() to choose override vs base

    The override table contains AggregateFunction states, so the join function uses merge functions
    (argMinMerge, argMaxMerge, etc.) to read them.
    """
    # Step 1: Add hidden soe_* fields to events table
    add_hidden_soe_fields_to_events_table(events_table)

    # Step 2: Add virtual table that exposes session properties
    session_sub_table = EventsSessionSubTable()
    add_session_properties_to_session_sub_table(session_sub_table)
    events_table.fields["session_on_events"] = session_sub_table

    # Step 3: Add lazy join to overrides table (only materialized if session properties accessed)
    events_table.fields["session_overrides"] = LazyJoin(
        from_field=["$session_id_uuid"],
        join_table=SessionsOnEventsOverridesTable(),
        join_function=join_with_sessions_on_events_overrides,
    )

    # Step 4: Point events.session to the session_on_events virtual table
    events_table.fields["session"] = FieldTraverser(chain=["session_on_events"])

    # Step 5: Replace each field in session_on_events with ExpressionFields that use override logic
    # Timestamps - use least/greatest to merge with overrides
    session_sub_table.fields["$start_timestamp"] = ExpressionField(
        name="$start_timestamp",
        expr=parse_expr(
            "if(isNotNull(session_overrides.min_timestamp), "
            "least(soe_min_timestamp, session_overrides.min_timestamp), "
            "soe_min_timestamp)",
            start=None,
        ),
        isolate_scope=True,
    )

    session_sub_table.fields["$end_timestamp"] = ExpressionField(
        name="$end_timestamp",
        expr=parse_expr(
            "if(isNotNull(session_overrides.max_timestamp), "
            "greatest(soe_max_timestamp, session_overrides.max_timestamp), "
            "soe_max_timestamp)",
            start=None,
        ),
        isolate_scope=True,
    )

    # Duration - computed from timestamps
    session_sub_table.fields["duration"] = ExpressionField(
        name="duration",
        expr=parse_expr(
            "dateDiff('second', "
            "if(isNotNull(session_overrides.min_timestamp), "
            "  least(soe_min_timestamp, session_overrides.min_timestamp), "
            "  soe_min_timestamp), "
            "if(isNotNull(session_overrides.max_timestamp), "
            "  greatest(soe_max_timestamp, session_overrides.max_timestamp), "
            "  soe_max_timestamp)"
            ")",
            start=None,
        ),
        isolate_scope=True,
    )

    # URLs - use override if present (based on pageview_prio_timestamp_min comparison)
    session_sub_table.fields["$entry_current_url"] = ExpressionField(
        name="$entry_current_url",
        expr=parse_expr(
            "if(isNotNull(session_overrides.entry_url), session_overrides.entry_url, soe_entry_url)", start=None
        ),
        isolate_scope=True,
    )

    session_sub_table.fields["$end_current_url"] = ExpressionField(
        name="$end_current_url",
        expr=parse_expr("if(isNotNull(session_overrides.end_url), session_overrides.end_url, soe_end_url)", start=None),
        isolate_scope=True,
    )

    session_sub_table.fields["$last_external_click_url"] = ExpressionField(
        name="$last_external_click_url",
        expr=parse_expr(
            "if(isNotNull(session_overrides.last_external_click_url), "
            "session_overrides.last_external_click_url, soe_last_external_click_url)",
            start=None,
        ),
        isolate_scope=True,
    )

    # Attribution fields - use override if present
    for attr_field in [
        "entry_referring_domain",
        "entry_utm_source",
        "entry_utm_campaign",
        "entry_utm_medium",
        "entry_utm_term",
        "entry_utm_content",
        "entry_gclid",
        "entry_gad_source",
        "entry_fbclid",
    ]:
        hogql_field = f"${attr_field}"
        soe_field = f"soe_{attr_field}"
        session_sub_table.fields[hogql_field] = ExpressionField(
            name=hogql_field,
            expr=parse_expr(
                f"if(isNotNull(session_overrides.{attr_field}), session_overrides.{attr_field}, {soe_field})",
                start=None,
            ),
            isolate_scope=True,
        )

    # Boolean flags - use OR to merge
    for bool_field in ["entry_has_gclid", "entry_has_fbclid", "has_autocapture", "has_replay"]:
        hogql_field = f"${bool_field}"
        soe_field = f"soe_{bool_field}"
        session_sub_table.fields[hogql_field] = ExpressionField(
            name=hogql_field,
            expr=parse_expr(
                f"if(isNotNull(session_overrides.{bool_field}), "
                f"session_overrides.{bool_field} OR {soe_field}, {soe_field})",
                start=None,
            ),
            isolate_scope=True,
        )
