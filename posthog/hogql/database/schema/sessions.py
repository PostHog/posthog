from typing import cast, Any, Optional, TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    StringDatabaseField,
    DateTimeDatabaseField,
    IntegerDatabaseField,
    Table,
    FieldOrTable,
    StringArrayDatabaseField,
    DatabaseField,
    LazyTable,
    FloatDatabaseField,
    BooleanDatabaseField,
)
from posthog.hogql.database.schema.channel_type import create_channel_type_expr, POSSIBLE_CHANNEL_TYPES
from posthog.hogql.database.schema.util.session_where_clause_extractor import SessionMinTimestampWhereClauseExtractor
from posthog.hogql.errors import ResolutionError
from posthog.models.property_definition import PropertyType
from posthog.models.sessions.sql import (
    SELECT_SESSION_PROP_STRING_VALUES_SQL_WITH_FILTER,
    SELECT_SESSION_PROP_STRING_VALUES_SQL,
)
from posthog.queries.insight import insight_sync_execute

if TYPE_CHECKING:
    from posthog.models.team import Team

RAW_SESSIONS_FIELDS: dict[str, FieldOrTable] = {
    "id": StringDatabaseField(name="session_id"),
    # TODO remove this, it's a duplicate of the correct session_id field below to get some trends working on a deadline
    "session_id": StringDatabaseField(name="session_id"),
    "team_id": IntegerDatabaseField(name="team_id"),
    "distinct_id": StringDatabaseField(name="distinct_id"),
    "min_timestamp": DateTimeDatabaseField(name="min_timestamp"),
    "max_timestamp": DateTimeDatabaseField(name="max_timestamp"),
    "urls": StringArrayDatabaseField(name="urls"),
    # many of the fields in the raw tables are AggregateFunction state, rather than simple types
    "entry_url": DatabaseField(name="entry_url"),
    "exit_url": DatabaseField(name="exit_url"),
    "initial_utm_source": DatabaseField(name="initial_utm_source"),
    "initial_utm_campaign": DatabaseField(name="initial_utm_campaign"),
    "initial_utm_medium": DatabaseField(name="initial_utm_medium"),
    "initial_utm_term": DatabaseField(name="initial_utm_term"),
    "initial_utm_content": DatabaseField(name="initial_utm_content"),
    "initial_referring_domain": DatabaseField(name="initial_referring_domain"),
    "initial_gclid": DatabaseField(name="initial_gclid"),
    "initial_gad_source": DatabaseField(name="initial_gad_source"),
    "event_count_map": DatabaseField(name="event_count_map"),
    "pageview_count": IntegerDatabaseField(name="pageview_count"),
    "autocapture_count": IntegerDatabaseField(name="autocapture_count"),
}

LAZY_SESSIONS_FIELDS: dict[str, FieldOrTable] = {
    "id": StringDatabaseField(name="session_id"),
    # TODO remove this, it's a duplicate of the correct session_id field below to get some trends working on a deadline
    "session_id": StringDatabaseField(name="session_id"),
    "team_id": IntegerDatabaseField(name="team_id"),
    "distinct_id": StringDatabaseField(name="distinct_id"),
    "$start_timestamp": DateTimeDatabaseField(name="$start_timestamp"),
    "$end_timestamp": DateTimeDatabaseField(name="$end_timestamp"),
    "$urls": StringArrayDatabaseField(name="$urls"),
    "$entry_url": StringDatabaseField(name="$entry_url"),
    "$entry_pathname": StringDatabaseField(name="$entry_pathname"),
    "$exit_url": StringDatabaseField(name="$exit_url"),
    "$exit_pathname": StringDatabaseField(name="$exit_pathname"),
    "$initial_utm_source": StringDatabaseField(name="$initial_utm_source"),
    "$initial_utm_campaign": StringDatabaseField(name="$initial_utm_campaign"),
    "$initial_utm_medium": StringDatabaseField(name="$initial_utm_medium"),
    "$initial_utm_term": StringDatabaseField(name="$initial_utm_term"),
    "$initial_utm_content": StringDatabaseField(name="$initial_utm_content"),
    "$initial_referring_domain": StringDatabaseField(name="$initial_referring_domain"),
    "$initial_gclid": StringDatabaseField(name="$initial_gclid"),
    "$initial_gad_source": StringDatabaseField(name="$initial_gad_source"),
    "$event_count_map": DatabaseField(name="$event_count_map"),
    "$pageview_count": IntegerDatabaseField(name="$pageview_count"),
    "$autocapture_count": IntegerDatabaseField(name="$autocapture_count"),
    "$channel_type": StringDatabaseField(name="$channel_type"),
    "$session_duration": IntegerDatabaseField(name="$session_duration"),
    "duration": IntegerDatabaseField(
        name="duration"
    ),  # alias of $session_duration, deprecated but included for backwards compatibility
    "$is_bounce": BooleanDatabaseField(name="$is_bounce"),
}


class RawSessionsTable(Table):
    fields: dict[str, FieldOrTable] = RAW_SESSIONS_FIELDS

    def to_printed_clickhouse(self, context):
        return "sessions"

    def to_printed_hogql(self):
        return "raw_sessions"

    def avoid_asterisk_fields(self) -> list[str]:
        # our clickhouse driver can't return aggregate states
        return [
            "entry_url",
            "exit_url",
            "initial_utm_source",
            "initial_utm_campaign",
            "initial_utm_medium",
            "initial_utm_term",
            "initial_utm_content",
            "initial_referring_domain",
            "initial_gclid",
            "initial_gad_source",
        ]


def select_from_sessions_table(
    requested_fields: dict[str, list[str | int]], node: ast.SelectQuery, context: HogQLContext
):
    from posthog.hogql import ast

    table_name = "raw_sessions"

    # Always include "session_id", as it's the key we use to make further joins, and it'd be great if it's available
    if "session_id" not in requested_fields:
        requested_fields = {**requested_fields, "session_id": ["session_id"]}

    aggregate_fields: dict[str, ast.Expr] = {
        "distinct_id": ast.Call(name="any", args=[ast.Field(chain=[table_name, "distinct_id"])]),
        "$start_timestamp": ast.Call(name="min", args=[ast.Field(chain=[table_name, "min_timestamp"])]),
        "$end_timestamp": ast.Call(name="max", args=[ast.Field(chain=[table_name, "max_timestamp"])]),
        "$urls": ast.Call(
            name="arrayDistinct",
            args=[
                ast.Call(
                    name="arrayFlatten",
                    args=[ast.Call(name="groupArray", args=[ast.Field(chain=[table_name, "urls"])])],
                )
            ],
        ),
        "$entry_url": ast.Call(name="argMinMerge", args=[ast.Field(chain=[table_name, "entry_url"])]),
        "$entry_pathname": ast.Call(
            name="path", args=[ast.Call(name="argMinMerge", args=[ast.Field(chain=[table_name, "entry_url"])])]
        ),
        "$exit_url": ast.Call(name="argMaxMerge", args=[ast.Field(chain=[table_name, "exit_url"])]),
        "$exit_pathname": ast.Call(
            name="path",
            args=[
                ast.Call(name="argMaxMerge", args=[ast.Field(chain=[table_name, "exit_url"])]),
            ],
        ),
        "$initial_utm_source": ast.Call(name="argMinMerge", args=[ast.Field(chain=[table_name, "initial_utm_source"])]),
        "$initial_utm_campaign": ast.Call(
            name="argMinMerge", args=[ast.Field(chain=[table_name, "initial_utm_campaign"])]
        ),
        "$initial_utm_medium": ast.Call(name="argMinMerge", args=[ast.Field(chain=[table_name, "initial_utm_medium"])]),
        "$initial_utm_term": ast.Call(name="argMinMerge", args=[ast.Field(chain=[table_name, "initial_utm_term"])]),
        "$initial_utm_content": ast.Call(
            name="argMinMerge", args=[ast.Field(chain=[table_name, "initial_utm_content"])]
        ),
        "$initial_referring_domain": ast.Call(
            name="argMinMerge", args=[ast.Field(chain=[table_name, "initial_referring_domain"])]
        ),
        "$initial_gclid": ast.Call(name="argMinMerge", args=[ast.Field(chain=[table_name, "initial_gclid"])]),
        "$initial_gad_source": ast.Call(name="argMinMerge", args=[ast.Field(chain=[table_name, "initial_gad_source"])]),
        "$event_count_map": ast.Call(
            name="sumMap",
            args=[ast.Field(chain=[table_name, "event_count_map"])],
        ),
        "$pageview_count": ast.Call(name="sum", args=[ast.Field(chain=[table_name, "pageview_count"])]),
        "$autocapture_count": ast.Call(name="sum", args=[ast.Field(chain=[table_name, "autocapture_count"])]),
    }
    # Some fields are calculated from others. It'd be good to actually deduplicate common sub expressions in SQL, but
    # for now just remove the duplicate definitions from the code
    aggregate_fields["$session_duration"] = ast.Call(
        name="dateDiff",
        args=[
            ast.Constant(value="second"),
            aggregate_fields["$start_timestamp"],
            aggregate_fields["$end_timestamp"],
        ],
    )
    aggregate_fields["duration"] = aggregate_fields["$session_duration"]
    aggregate_fields["$is_bounce"] = ast.Call(
        name="if",
        args=[
            ast.Call(name="equals", args=[aggregate_fields["$pageview_count"], ast.Constant(value=0)]),
            ast.Constant(value=None),
            ast.Call(
                name="not",
                args=[
                    ast.Call(
                        name="or",
                        args=[
                            ast.Call(name="greater", args=[aggregate_fields["$pageview_count"], ast.Constant(value=1)]),
                            ast.Call(
                                name="greater", args=[aggregate_fields["$autocapture_count"], ast.Constant(value=0)]
                            ),
                            ast.Call(
                                name="greaterOrEquals",
                                args=[aggregate_fields["$session_duration"], ast.Constant(value=10)],
                            ),
                        ],
                    )
                ],
            ),
        ],
    )
    aggregate_fields["$channel_type"] = create_channel_type_expr(
        campaign=aggregate_fields["$initial_utm_campaign"],
        medium=aggregate_fields["$initial_utm_medium"],
        source=aggregate_fields["$initial_utm_source"],
        referring_domain=aggregate_fields["$initial_referring_domain"],
        gclid=aggregate_fields["$initial_gclid"],
        gad_source=aggregate_fields["$initial_gad_source"],
    )

    select_fields: list[ast.Expr] = []
    group_by_fields: list[ast.Expr] = [ast.Field(chain=[table_name, "session_id"])]

    for name, chain in requested_fields.items():
        if name in aggregate_fields:
            select_fields.append(ast.Alias(alias=name, expr=aggregate_fields[name]))
        else:
            select_fields.append(
                ast.Alias(alias=name, expr=ast.Field(chain=cast(list[str | int], [table_name]) + chain))
            )
            group_by_fields.append(ast.Field(chain=cast(list[str | int], [table_name]) + chain))

    where = SessionMinTimestampWhereClauseExtractor(context).get_inner_where(node)

    return ast.SelectQuery(
        select=select_fields,
        select_from=ast.JoinExpr(table=ast.Field(chain=[table_name])),
        group_by=group_by_fields,
        where=where,
    )


class SessionsTable(LazyTable):
    fields: dict[str, FieldOrTable] = LAZY_SESSIONS_FIELDS

    def lazy_select(self, requested_fields: dict[str, list[str | int]], context, node: ast.SelectQuery):
        return select_from_sessions_table(requested_fields, node, context)

    def to_printed_clickhouse(self, context):
        return "sessions"

    def to_printed_hogql(self):
        return "sessions"

    def avoid_asterisk_fields(self) -> list[str]:
        return [
            "duration",  # alias of $session_duration, deprecated but included for backwards compatibility
        ]


def join_events_table_to_sessions_table(
    from_table: str, to_table: str, requested_fields: dict[str, Any], context: HogQLContext, node: ast.SelectQuery
) -> ast.JoinExpr:
    from posthog.hogql import ast

    if not requested_fields:
        raise ResolutionError("No fields requested from events")

    join_expr = ast.JoinExpr(table=select_from_sessions_table(requested_fields, node, context))
    join_expr.join_type = "LEFT JOIN"
    join_expr.alias = to_table
    join_expr.constraint = ast.JoinConstraint(
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[from_table, "$session_id"]),
            right=ast.Field(chain=[to_table, "session_id"]),
        )
    )
    return join_expr


def get_lazy_session_table_properties(search: Optional[str]):
    # some fields shouldn't appear as properties
    hidden_fields = {"team_id", "distinct_id", "session_id", "id", "$event_count_map", "$urls", "duration"}

    # some fields should have a specific property type which isn't derivable from the type of database field
    property_type_overrides = {
        "$session_duration": PropertyType.Duration,
    }

    def get_property_type(field_name: str, field_definition: FieldOrTable):
        if field_name in property_type_overrides:
            return property_type_overrides[field_name]
        if isinstance(field_definition, IntegerDatabaseField) or isinstance(field_definition, FloatDatabaseField):
            return PropertyType.Numeric
        if isinstance(field_definition, DateTimeDatabaseField):
            return PropertyType.Datetime
        if isinstance(field_definition, BooleanDatabaseField):
            return PropertyType.Boolean
        return PropertyType.String

    results = [
        {
            "id": field_name,
            "name": field_name,
            "is_numerical": isinstance(field_definition, IntegerDatabaseField)
            or isinstance(field_definition, FloatDatabaseField),
            "property_type": get_property_type(field_name, field_definition),
            "is_seen_on_filtered_events": None,
            "tags": [],
        }
        for field_name, field_definition in LAZY_SESSIONS_FIELDS.items()
        if (not search or search.lower() in field_name.lower()) and field_name not in hidden_fields
    ]
    return results


SESSION_PROPERTY_TO_RAW_SESSIONS_EXPR_MAP = {
    "$initial_referring_domain": "finalizeAggregation(initial_referring_domain)",
    "$initial_utm_source": "finalizeAggregation(initial_utm_source)",
    "$initial_utm_campaign": "finalizeAggregation(initial_utm_campaign)",
    "$initial_utm_medium": "finalizeAggregation(initial_utm_medium)",
    "$initial_utm_term": "finalizeAggregation(initial_utm_term)",
    "$initial_utm_content": "finalizeAggregation(initial_utm_content)",
    "$initial_gclid": "finalizeAggregation(initial_gclid)",
    "$initial_gad_source": "finalizeAggregation(initial_gad_source)",
    "$initial_gclsrc": "finalizeAggregation(initial_gclsrc)",
    "$initial_dclid": "finalizeAggregation(initial_dclid)",
    "$initial_gbraid": "finalizeAggregation(initial_gbraid)",
    "$initial_wbraid": "finalizeAggregation(initial_wbraid)",
    "$initial_fbclid": "finalizeAggregation(initial_fbclid)",
    "$initial_msclkid": "finalizeAggregation(initial_msclkid)",
    "$initial_twclid": "finalizeAggregation(initial_twclid)",
    "$initial_li_fat_id": "finalizeAggregation(initial_li_fat_id)",
    "$initial_mc_cid": "finalizeAggregation(initial_mc_cid)",
    "$initial_igshid": "finalizeAggregation(initial_igshid)",
    "$initial_ttclid": "finalizeAggregation(initial_ttclid)",
    "$entry_url": "finalizeAggregation(entry_url)",
    "$exit_url": "finalizeAggregation(exit_url)",
}


def get_lazy_session_table_values(key: str, search_term: Optional[str], team: "Team"):
    # the sessions table does not have a properties json object like the events and person tables

    if key == "$channel_type":
        return [[name] for name in POSSIBLE_CHANNEL_TYPES if not search_term or search_term.lower() in name.lower()]

    field_definition = LAZY_SESSIONS_FIELDS.get(key)
    if not field_definition:
        return []

    if isinstance(field_definition, StringDatabaseField):
        expr = SESSION_PROPERTY_TO_RAW_SESSIONS_EXPR_MAP.get(key)

        if not expr:
            return []

        if search_term:
            return insight_sync_execute(
                SELECT_SESSION_PROP_STRING_VALUES_SQL_WITH_FILTER.format(property_expr=expr),
                {"team_id": team.pk, "key": key, "value": "%{}%".format(search_term)},
                query_type="get_session_property_values_with_value",
                team_id=team.pk,
            )
        return insight_sync_execute(
            SELECT_SESSION_PROP_STRING_VALUES_SQL.format(property_expr=expr),
            {"team_id": team.pk, "key": key},
            query_type="get_session_property_values",
            team_id=team.pk,
        )
    if isinstance(field_definition, BooleanDatabaseField):
        # ideally we'd be able to just send [[True], [False]]
        return [["1"], ["0"]]

    return []
