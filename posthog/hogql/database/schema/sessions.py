from typing import Dict, List

from posthog.hogql.database.models import (
    StringDatabaseField,
    DateTimeDatabaseField,
    IntegerDatabaseField,
    Table,
    FieldOrTable,
    StringArrayDatabaseField,
    DatabaseField,
    LazyTable,
)
from posthog.schema import HogQLQueryModifiers


SESSIONS_COMMON_FIELDS: Dict[str, FieldOrTable] = {
    "session_id": StringDatabaseField(name="session_id"),
    "team_id": IntegerDatabaseField(name="team_id"),
    "distinct_id": StringDatabaseField(name="distinct_id"),
    "min_timestamp": DateTimeDatabaseField(name="min_timestamp"),
    "max_timestamp": DateTimeDatabaseField(name="max_timestamp"),
    "urls": StringArrayDatabaseField(name="urls"),
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


class RawSessionsTable(Table):
    fields: Dict[str, FieldOrTable] = SESSIONS_COMMON_FIELDS

    def to_printed_clickhouse(self, context):
        return "sessions"

    def to_printed_hogql(self):
        return "raw_sessions"

    def avoid_asterisk_fields(self) -> List[str]:
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


def select_from_sessions_table(requested_fields: Dict[str, List[str]]):
    from posthog.hogql import ast

    table_name = "raw_sessions"

    aggregate_fields = {
        "distinct_id": ast.Call(name="any", args=[ast.Field(chain=[table_name, "distinct_id"])]),
        "min_timestamp": ast.Call(name="min", args=[ast.Field(chain=[table_name, "min_timestamp"])]),
        "max_timestamp": ast.Call(name="max", args=[ast.Field(chain=[table_name, "max_timestamp"])]),
        "urls": ast.Call(
            name="arrayDistinct",
            args=[
                ast.Call(
                    name="arrayFlatten",
                    args=[ast.Call(name="groupArray", args=[ast.Field(chain=[table_name, "urls"])])],
                )
            ],
        ),
        "entry_url": ast.Call(name="argMinMerge", args=[ast.Field(chain=[table_name, "entry_url"])]),
        "exit_url": ast.Call(name="argMaxMerge", args=[ast.Field(chain=[table_name, "exit_url"])]),
        "initial_utm_source": ast.Call(name="argMinMerge", args=[ast.Field(chain=[table_name, "initial_utm_source"])]),
        "initial_utm_campaign": ast.Call(
            name="argMinMerge", args=[ast.Field(chain=[table_name, "initial_utm_campaign"])]
        ),
        "initial_utm_medium": ast.Call(name="argMinMerge", args=[ast.Field(chain=[table_name, "initial_utm_medium"])]),
        "initial_utm_term": ast.Call(name="argMinMerge", args=[ast.Field(chain=[table_name, "initial_utm_term"])]),
        "initial_utm_content": ast.Call(
            name="argMinMerge", args=[ast.Field(chain=[table_name, "initial_utm_content"])]
        ),
        "initial_referring_domain": ast.Call(
            name="argMinMerge", args=[ast.Field(chain=[table_name, "initial_referring_domain"])]
        ),
        "initial_gclid": ast.Call(name="argMinMerge", args=[ast.Field(chain=[table_name, "initial_gclid"])]),
        "initial_gad_source": ast.Call(name="argMinMerge", args=[ast.Field(chain=[table_name, "initial_gad_source"])]),
        "event_count_map": ast.Call(
            name="sumMap",
            args=[ast.Field(chain=[table_name, "event_count_map"])],
        ),
        "pageview_count": ast.Call(name="sum", args=[ast.Field(chain=[table_name, "pageview_count"])]),
        "autocapture_count": ast.Call(name="sum", args=[ast.Field(chain=[table_name, "autocapture_count"])]),
        "duration": ast.Call(
            name="dateDiff",
            args=[
                ast.Constant(value="second"),
                ast.Call(name="min", args=[ast.Field(chain=[table_name, "min_timestamp"])]),
                ast.Call(name="max", args=[ast.Field(chain=[table_name, "max_timestamp"])]),
            ],
        ),
    }

    select_fields: List[ast.Expr] = []
    group_by_fields: List[ast.Expr] = [ast.Field(chain=[table_name, "session_id"])]

    for name, chain in requested_fields.items():
        if name in aggregate_fields:
            select_fields.append(ast.Alias(alias=name, expr=aggregate_fields[name]))
        else:
            select_fields.append(ast.Alias(alias=name, expr=ast.Field(chain=[table_name] + chain)))
            group_by_fields.append(ast.Field(chain=[table_name] + chain))

    return ast.SelectQuery(
        select=select_fields,
        select_from=ast.JoinExpr(table=ast.Field(chain=[table_name])),
        group_by=group_by_fields,
    )


class SessionsTable(LazyTable):
    fields: Dict[str, FieldOrTable] = {
        **SESSIONS_COMMON_FIELDS,
        "duration": IntegerDatabaseField(name="duration"),
    }

    def lazy_select(self, requested_fields: Dict[str, List[str]], modifiers: HogQLQueryModifiers):
        return select_from_sessions_table(requested_fields)

    def to_printed_clickhouse(self, context):
        return "sessions"

    def to_printed_hogql(self):
        return "sessions"
