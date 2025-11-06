import re
from typing import TYPE_CHECKING, Optional, cast

from posthog.schema import CustomChannelRule

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    LazyJoinToAdd,
    LazyTable,
    LazyTableToAdd,
    StringArrayDatabaseField,
    StringDatabaseField,
    Table,
    UUIDDatabaseField,
)
from posthog.hogql.database.schema.channel_type import DEFAULT_CHANNEL_TYPES, ChannelTypeExprs, create_channel_type_expr
from posthog.hogql.database.schema.sessions_v1 import DEFAULT_BOUNCE_RATE_DURATION_SECONDS
from posthog.hogql.database.schema.util.where_clause_extractor import SessionMinTimestampWhereClauseExtractorV3
from posthog.hogql.errors import ResolutionError
from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.models.property_definition import PropertyType
from posthog.models.raw_sessions.sessions_v3 import (
    RAW_SELECT_SESSION_PROP_STRING_VALUES_SQL_V3,
    RAW_SELECT_SESSION_PROP_STRING_VALUES_SQL_WITH_FILTER_V3,
    SESSION_V3_LOWER_TIER_AD_IDS,
)
from posthog.queries.insight import insight_sync_execute

if TYPE_CHECKING:
    from posthog.models.team import Team


RAW_SESSIONS_FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id", nullable=False),
    "session_id_v7": UUIDDatabaseField(name="session_id_v7", nullable=False),
    "session_timestamp": DatabaseField(
        name="session_timestamp", nullable=False
    ),  # not a DateTimeDatabaseField to avoid wrapping with toTimeZone
    "distinct_id": DatabaseField(name="distinct_id", nullable=False),
    "min_timestamp": DateTimeDatabaseField(name="min_timestamp", nullable=False),
    "max_timestamp": DateTimeDatabaseField(name="max_timestamp", nullable=False),
    "max_inserted_at": DateTimeDatabaseField(name="max_inserted_at", nullable=False),
    "urls": StringArrayDatabaseField(name="urls", nullable=False),
    "entry_url": DatabaseField(name="entry_url", nullable=False),
    "end_url": DatabaseField(name="end_url", nullable=False),
    "last_external_click_url": DatabaseField(name="last_external_click_url", nullable=False),
    "browser": DatabaseField(name="browser", nullable=False),
    "browser_version": DatabaseField(name="browser_version", nullable=False),
    "os": DatabaseField(name="os", nullable=False),
    "os_version": DatabaseField(name="os_version", nullable=False),
    "device_type": DatabaseField(name="device_type", nullable=False),
    "viewport_width": DatabaseField(name="viewport_width", nullable=False),
    "viewport_height": DatabaseField(name="viewport_height", nullable=False),
    "geoip_country_code": DatabaseField(name="geoip_country_code", nullable=False),
    "geoip_subdivision_1_code": DatabaseField(name="geoip_subdivision_1_code", nullable=False),
    "geoip_subdivision_1_name": DatabaseField(name="geoip_subdivision_1_name", nullable=False),
    "geoip_subdivision_city_name": DatabaseField(name="geoip_subdivision_city_name", nullable=False),
    "geoip_time_zone": DatabaseField(name="geoip_time_zone", nullable=False),
    "entry_referring_domain": DatabaseField(name="entry_referring_domain", nullable=False),
    "entry_utm_source": DatabaseField(name="entry_utm_source", nullable=False),
    "entry_utm_campaign": DatabaseField(name="entry_utm_campaign", nullable=False),
    "entry_utm_medium": DatabaseField(name="entry_utm_medium", nullable=False),
    "entry_utm_term": DatabaseField(name="entry_utm_term", nullable=False),
    "entry_utm_content": DatabaseField(name="entry_utm_content", nullable=False),
    "entry_gclid": DatabaseField(name="entry_gclid", nullable=False),
    "entry_gad_source": DatabaseField(name="entry_gad_source", nullable=False),
    "entry_fbclid": DatabaseField(name="entry_fbclid", nullable=False),
    "entry_has_gclid": DatabaseField(name="entry_has_gclid", nullable=False),
    "entry_has_fbclid": DatabaseField(name="entry_has_fbclid", nullable=False),
    "entry_ad_ids_map": DatabaseField(name="entry_ad_ids_map", nullable=False),
    "entry_ad_ids_set": DatabaseField(name="entry_ad_ids_set", nullable=False),
    "entry_channel_type_properties": DatabaseField(name="entry_channel_type_properties", nullable=False),
    "pageview_uniq": DatabaseField(name="pageview_uniq", nullable=False),
    "autocapture_uniq": DatabaseField(name="autocapture_uniq", nullable=False),
    "screen_uniq": DatabaseField(name="screen_uniq", nullable=False),
    "page_screen_uniq_up_to": DatabaseField(name="page_screen_uniq_up_to", nullable=False),
    "has_autocapture": BooleanDatabaseField(name="has_autocapture", nullable=False),
    "has_replay_events": BooleanDatabaseField(name="has_replay_events", nullable=False),
}

LAZY_SESSIONS_FIELDS: dict[str, FieldOrTable] = {
    # IDs
    "team_id": IntegerDatabaseField(name="team_id"),
    "session_id_v7": StringDatabaseField(name="session_id_v7"),
    "id": StringDatabaseField(name="id"),
    # TODO remove this, it's a duplicate of the correct session_id field below to get some trends working on a deadline
    "session_id": StringDatabaseField(name="session_id"),
    "session_timestamp": DateTimeDatabaseField(name="session_timestamp", nullable=False),
    "distinct_id": StringDatabaseField(name="distinct_id"),
    # timestamp
    "$start_timestamp": DateTimeDatabaseField(name="$start_timestamp"),
    "$end_timestamp": DateTimeDatabaseField(name="$end_timestamp"),
    "max_inserted_at": DateTimeDatabaseField(name="max_inserted_at"),
    # URLs
    "$urls": StringArrayDatabaseField(name="$urls"),
    "$num_uniq_urls": IntegerDatabaseField(name="$num_uniq_urls"),
    "$entry_current_url": StringDatabaseField(name="$entry_current_url"),
    "$entry_pathname": StringDatabaseField(name="$entry_pathname"),
    "$entry_hostname": StringDatabaseField(name="$entry_host"),
    "$end_current_url": StringDatabaseField(name="$end_current_url"),
    "$end_pathname": StringDatabaseField(name="$end_pathname"),
    "$end_hostname": StringDatabaseField(name="$end_hostname"),
    "$entry_referring_domain": StringDatabaseField(name="$entry_referring_domain"),
    "$last_external_click_url": StringDatabaseField(name="$last_external_click_url"),
    # some aliases for people upgrading from v1 to v2/v3
    "$exit_current_url": StringDatabaseField(name="$exit_current_url"),
    "$exit_pathname": StringDatabaseField(name="$exit_pathname"),
    # UTM parameters
    "$entry_utm_source": StringDatabaseField(name="$entry_utm_source"),
    "$entry_utm_campaign": StringDatabaseField(name="$entry_utm_campaign"),
    "$entry_utm_medium": StringDatabaseField(name="$entry_utm_medium"),
    "$entry_utm_term": StringDatabaseField(name="$entry_utm_term"),
    "$entry_utm_content": StringDatabaseField(name="$entry_utm_content"),
    "$entry_fbclid": StringDatabaseField(name="$entry_fbclid"),
    "$entry_gclid": DatabaseField(name="$entry_gclid"),
    "$entry_gad_source": DatabaseField(name="$entry_gad_source"),
    "$entry_has_fbclid": BooleanDatabaseField(name="$entry_has_fbclid"),
    "$entry_has_gclid": BooleanDatabaseField(name="$entry_has_gclid"),
    # "counts" - actually uses uniqExact behind the scenes
    "$pageview_count": IntegerDatabaseField(name="$pageview_count"),
    "$autocapture_count": IntegerDatabaseField(name="$autocapture_count"),
    "$screen_count": IntegerDatabaseField(name="$screen_count"),
    # some perf optimisation columns
    "$page_screen_count_up_to": DatabaseField(name="$page_screen_count_up_to"),
    "$has_autocapture": BooleanDatabaseField(name="$has_autocapture"),
    "$entry_channel_type_properties": DatabaseField(name="$entry_channel_type_properties"),
    # computed fields
    "$channel_type": StringDatabaseField(name="$channel_type"),
    "$session_duration": IntegerDatabaseField(name="$session_duration"),
    "duration": IntegerDatabaseField(
        name="duration"
    ),  # alias of $session_duration, deprecated but included for backwards compatibility
    "$is_bounce": BooleanDatabaseField(name="$is_bounce"),
    "$has_replay_events": BooleanDatabaseField(name="$has_replay_events", nullable=False),
}


for session_ad_id in SESSION_V3_LOWER_TIER_AD_IDS:
    LAZY_SESSIONS_FIELDS["$entry_" + session_ad_id] = StringDatabaseField(name="$entry_" + session_ad_id)
    LAZY_SESSIONS_FIELDS["$entry_has_" + session_ad_id] = BooleanDatabaseField(name="$entry_has_" + session_ad_id)


def get_binary_fields(table: Table) -> set[str]:
    return {key for key, val in table.fields.items() if val.__class__ == DatabaseField}


class RawSessionsTableV3(Table):
    fields: dict[str, FieldOrTable] = RAW_SESSIONS_FIELDS

    def to_printed_clickhouse(self, context):
        return "raw_sessions_v3"

    def to_printed_hogql(self):
        return "raw_sessions_v3"

    def avoid_asterisk_fields(self) -> list[str]:
        return list(
            {
                *get_binary_fields(self),  # our clickhouse driver can't return aggregate states
                "session_id_v7",  # HogQL insights currently don't support returning uint128s due to json serialisation
            }
        )


def select_from_sessions_table_v3(
    requested_fields: dict[str, list[str | int]], node: ast.SelectQuery, context: HogQLContext
):
    from posthog.hogql import ast

    table_name = "raw_sessions_v3"

    # Always include "session_id", as it's the key we use to make further joins, and it'd be great if it's available
    if "session_id_v7" not in requested_fields:
        requested_fields = {**requested_fields, "session_id_v7": ["session_id_v7"]}

    def arg_min_merge_field(field_name: str) -> ast.Call:
        return ast.Call(name="argMinMerge", args=[ast.Field(chain=[table_name, field_name])])

    def arg_max_merge_field(field_name: str) -> ast.Call:
        return ast.Call(name="argMaxMerge", args=[ast.Field(chain=[table_name, field_name])])

    aggregate_fields: dict[str, ast.Expr] = {
        "session_id": ast.Call(
            name="toString",
            args=[
                ast.Call(
                    name="reinterpretAsUUID",
                    args=[
                        ast.Call(
                            name="bitOr",
                            args=[
                                ast.Call(
                                    name="bitShiftLeft",
                                    args=[ast.Field(chain=[table_name, "session_id_v7"]), ast.Constant(value=64)],
                                ),
                                ast.Call(
                                    name="bitShiftRight",
                                    args=[ast.Field(chain=[table_name, "session_id_v7"]), ast.Constant(value=64)],
                                ),
                            ],
                        )
                    ],
                )
            ],
        ),  # try not to use this, prefer to use session_id_v7
        "distinct_id": arg_max_merge_field("distinct_id"),
        "$start_timestamp": ast.Call(name="min", args=[ast.Field(chain=[table_name, "min_timestamp"])]),
        "$end_timestamp": ast.Call(name="max", args=[ast.Field(chain=[table_name, "max_timestamp"])]),
        "max_inserted_at": ast.Call(name="max", args=[ast.Field(chain=[table_name, "max_inserted_at"])]),
        "$urls": ast.Call(
            name="arrayDistinct",
            args=[
                ast.Call(
                    name="arrayFlatten",
                    args=[ast.Call(name="groupArray", args=[ast.Field(chain=[table_name, "urls"])])],
                )
            ],
        ),
        "$entry_current_url": (arg_min_merge_field("entry_url")),
        "$end_current_url": (arg_max_merge_field("end_url")),
        "$last_external_click_url": arg_max_merge_field("last_external_click_url"),
        "$entry_utm_source": (arg_min_merge_field("entry_utm_source")),
        "$entry_utm_campaign": (arg_min_merge_field("entry_utm_campaign")),
        "$entry_utm_medium": (arg_min_merge_field("entry_utm_medium")),
        "$entry_utm_term": (arg_min_merge_field("entry_utm_term")),
        "$entry_utm_content": (arg_min_merge_field("entry_utm_content")),
        "$entry_referring_domain": (arg_min_merge_field("entry_referring_domain")),
        "$entry_gclid": (arg_min_merge_field("entry_gclid")),
        "$entry_gad_source": (arg_min_merge_field("entry_gad_source")),
        "$entry_fbclid": (arg_min_merge_field("entry_fbclid")),
        "$entry_has_gclid": arg_min_merge_field("entry_has_gclid"),
        "$entry_has_fbclid": arg_min_merge_field("entry_has_fbclid"),
        # the count columns here do not come from the "count" columns in the raw table, instead aggregate the uniq columns
        "$pageview_count": ast.Call(name="uniqExactMerge", args=[ast.Field(chain=[table_name, "pageview_uniq"])]),
        "$screen_count": ast.Call(name="uniqExactMerge", args=[ast.Field(chain=[table_name, "screen_uniq"])]),
        "$autocapture_count": ast.Call(name="uniqExactMerge", args=[ast.Field(chain=[table_name, "autocapture_uniq"])]),
        "$page_screen_count_up_to": ast.Call(
            name="uniqUpToMerge",
            params=[ast.Constant(value=1)],
            args=[ast.Field(chain=[table_name, "page_screen_uniq_up_to"])],
        ),
        "$has_autocapture": ast.Call(
            name="max",
            args=[ast.Field(chain=[table_name, "has_autocapture"])],
        ),
        "$entry_ad_ids_map": arg_min_merge_field("entry_ad_ids_map"),
        "$entry_ad_ids_set": arg_min_merge_field("entry_ad_ids_set"),
        "$entry_channel_type_properties": arg_min_merge_field("entry_channel_type_properties"),
        "$has_replay_events": ast.Call(name="max", args=[ast.Field(chain=[table_name, "has_replay_events"])]),
    }

    # Alias
    aggregate_fields["id"] = aggregate_fields["session_id"]

    # Add ad ids fields
    for session_ad_id in SESSION_V3_LOWER_TIER_AD_IDS:
        aggregate_fields["$entry_" + session_ad_id] = ast.Call(
            name="arrayElement",
            args=[
                aggregate_fields["$entry_ad_ids_map"],
                ast.Constant(value=session_ad_id),
            ],
        )
        aggregate_fields["$entry_has_" + session_ad_id] = ast.Call(
            name="has",
            args=[aggregate_fields["$entry_ad_ids_set"], ast.Constant(value=session_ad_id)],
        )

    # Some fields are calculated from others. It'd be good to actually deduplicate common sub expressions in SQL, but
    # for now just remove the duplicate definitions from the code
    aggregate_fields["$entry_pathname"] = ast.Call(
        name="path",
        args=[aggregate_fields["$entry_current_url"]],
    )
    aggregate_fields["$entry_hostname"] = ast.Call(
        name="domain",
        args=[aggregate_fields["$entry_current_url"]],
    )
    aggregate_fields["$end_pathname"] = ast.Call(
        name="path",
        args=[aggregate_fields["$end_current_url"]],
    )
    aggregate_fields["$end_hostname"] = ast.Call(
        name="domain",
        args=[aggregate_fields["$end_current_url"]],
    )
    aggregate_fields["$session_duration"] = ast.Call(
        name="dateDiff",
        args=[
            ast.Constant(value="second"),
            aggregate_fields["$start_timestamp"],
            aggregate_fields["$end_timestamp"],
        ],
    )
    aggregate_fields["duration"] = aggregate_fields["$session_duration"]
    aggregate_fields["$num_uniq_urls"] = ast.Call(
        name="length",
        args=[aggregate_fields["$urls"]],
    )

    bounce_rate_duration_seconds = (
        context.modifiers.bounceRateDurationSeconds
        if context.modifiers.bounceRateDurationSeconds is not None
        else DEFAULT_BOUNCE_RATE_DURATION_SECONDS
    )
    bounce_pageview_count = aggregate_fields["$page_screen_count_up_to"]
    aggregate_fields["$is_bounce"] = ast.Call(
        name="if",
        args=[
            # if the pageview/screen count is 0, return NULL, so it doesn't contribute towards the bounce rate either way
            ast.Call(name="equals", args=[bounce_pageview_count, ast.Constant(value=0)]),
            ast.Constant(value=None),
            ast.Call(
                name="not",
                args=[
                    ast.Call(
                        name="or",
                        args=[
                            # if >= 2 pageviews/screens, not a bounce
                            ast.Call(name="greater", args=[bounce_pageview_count, ast.Constant(value=1)]),
                            # if there was an autocapture, not a bounce
                            aggregate_fields["$has_autocapture"],
                            # if session duration >= bounce_rate_duration_seconds, not a bounce
                            ast.Call(
                                name="greaterOrEquals",
                                args=[
                                    aggregate_fields["$session_duration"],
                                    ast.Constant(value=bounce_rate_duration_seconds),
                                ],
                            ),
                        ],
                    )
                ],
            ),
        ],
    )

    def get_entry_channel_type_property(n: int):
        return ast.Call(
            name="tupleElement", args=[aggregate_fields["$entry_channel_type_properties"], ast.Constant(value=n)]
        )

    aggregate_fields["$channel_type"] = create_channel_type_expr(
        context.modifiers.customChannelTypeRules,
        ChannelTypeExprs(
            source=get_entry_channel_type_property(1),
            medium=get_entry_channel_type_property(2),
            campaign=get_entry_channel_type_property(3),
            referring_domain=get_entry_channel_type_property(4),
            has_gclid=get_entry_channel_type_property(5),
            has_fbclid=get_entry_channel_type_property(6),
            gad_source=get_entry_channel_type_property(7),
            url=aggregate_fields["$entry_current_url"],
            hostname=aggregate_fields["$entry_hostname"],
            pathname=aggregate_fields["$entry_pathname"],
        ),
        timings=context.timings,
    )
    # some aliases for people upgrading from v1 to v2/v3
    aggregate_fields["$exit_current_url"] = aggregate_fields["$end_current_url"]
    aggregate_fields["$exit_pathname"] = aggregate_fields["$end_pathname"]

    select_fields: list[ast.Expr] = []
    group_by_fields: list[ast.Expr] = []

    for name, chain in requested_fields.items():
        if name in aggregate_fields:
            select_fields.append(ast.Alias(alias=name, expr=aggregate_fields[name]))
        else:
            select_fields.append(
                ast.Alias(alias=name, expr=ast.Field(chain=cast(list[str | int], [table_name]) + chain))
            )
            group_by_fields.append(ast.Field(chain=cast(list[str | int], [table_name]) + chain))

    where = SessionMinTimestampWhereClauseExtractorV3(context).get_inner_where(node)

    return ast.SelectQuery(
        select=select_fields,
        select_from=ast.JoinExpr(table=ast.Field(chain=[table_name])),
        group_by=group_by_fields,
        where=where,
    )


class SessionsTableV3(LazyTable):
    fields: dict[str, FieldOrTable] = LAZY_SESSIONS_FIELDS

    def lazy_select(
        self,
        table_to_add: LazyTableToAdd,
        context,
        node: ast.SelectQuery,
    ):
        return select_from_sessions_table_v3(table_to_add.fields_accessed, node, context)

    def to_printed_clickhouse(self, context):
        return "sessions"

    def to_printed_hogql(self):
        return "sessions"

    def avoid_asterisk_fields(self) -> list[str]:
        return list(
            {
                *get_binary_fields(self),  # our clickhouse driver can't return aggregate states
                "session_id_v7",  # HogQL insights currently don't support returning uint128s due to json serialisation
                "id",  # prefer to use session_id
                "duration",  # alias of $session_duration, deprecated but included for backwards compatibility
                # aliases for people upgrading from v1 to v2
                "$exit_current_url",
                "$exit_pathname",
            }
        )


def session_id_to_session_id_v7_as_uuid_expr(session_id: ast.Expr) -> ast.Expr:
    return ast.Call(name="toUUID", args=[session_id])


def session_id_to_uint128_as_uuid_expr(session_id: ast.Expr) -> ast.Expr:
    return ast.Call(name="_toUInt128", args=[(session_id_to_session_id_v7_as_uuid_expr(session_id))])


def join_events_table_to_sessions_table_v3(
    join_to_add: LazyJoinToAdd, context: HogQLContext, node: ast.SelectQuery
) -> ast.JoinExpr:
    from posthog.hogql import ast

    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from events")

    join_expr = ast.JoinExpr(table=select_from_sessions_table_v3(join_to_add.fields_accessed, node, context))
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


def get_lazy_session_table_properties_v3(search: Optional[str]):
    # some fields shouldn't appear as properties
    hidden_fields = {
        "max_inserted_at",
        "team_id",
        "distinct_id",
        "session_id",
        "id",
        "session_id_v7",
        "$event_count_map",
        "$urls",
        "duration",
        "$num_uniq_urls",
        "$page_screen_autocapture_count_up_to",
        "$entry_channel_type_properties",
        "session_timestamp",  # really people should be using $start_timestamp for most queries
        # aliases for people upgrading from v1 to v2/v3
        "$exit_current_url",
        "$exit_pathname",
    }

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

    search_words = re.findall(r"\w+", search.lower()) if search else None

    def is_match(field_name: str) -> bool:
        if field_name in hidden_fields:
            return False
        if not search_words:
            return True
        return all(word in field_name.lower() for word in search_words)

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
        if is_match(field_name)
    ]
    return results


# NOTE: Keep the AD IDs in sync with `posthog.hogql_queries.web_analytics.session_attribution_explorer_query_runner.py`
SESSION_PROPERTY_TO_RAW_SESSIONS_EXPR_MAP = {
    "$entry_referring_domain": "finalizeAggregation(entry_referring_domain)",
    "$entry_utm_source": "finalizeAggregation(entry_utm_source)",
    "$entry_utm_campaign": "finalizeAggregation(entry_utm_campaign)",
    "$entry_utm_medium": "finalizeAggregation(entry_utm_medium)",
    "$entry_utm_term": "finalizeAggregation(entry_utm_term)",
    "$entry_utm_content": "finalizeAggregation(entry_utm_content)",
    "$entry_gclid": "finalizeAggregation(entry_gclid)",
    "$entry_gad_source": "finalizeAggregation(entry_gad_source)",
    "$entry_fbclid": "finalizeAggregation(entry_fbclid)",
    "$entry_current_url": "finalizeAggregation(entry_url)",
    "$entry_pathname": "path(finalizeAggregation(entry_url))",
    "$entry_hostname": "domain(finalizeAggregation(entry_url))",
    "$end_current_url": "finalizeAggregation(end_url)",
    "$end_pathname": "path(finalizeAggregation(end_url))",
    "$end_hostname": "domain(finalizeAggregation(end_url))",
    "$last_external_click_url": "finalizeAggregation(last_external_click_url)",
}

for session_ad_id in SESSION_V3_LOWER_TIER_AD_IDS:
    SESSION_PROPERTY_TO_RAW_SESSIONS_EXPR_MAP["$entry_" + session_ad_id] = (
        f"arrayElement(finalizeAggregation(entry_ad_ids_map), '{session_ad_id}')"
    )


def get_lazy_session_table_values_v3(key: str, search_term: Optional[str], team: "Team"):
    # the sessions table does not have a properties json object like the events and person tables

    if key == "$channel_type":
        modifiers = create_default_modifiers_for_team(team)
        custom_channel_type_rules: Optional[list[CustomChannelRule]] = modifiers.customChannelTypeRules
        if custom_channel_type_rules:
            custom_channel_types = [rule.channel_type for rule in custom_channel_type_rules]
        else:
            custom_channel_types = []
        default_channel_types = [
            entry for entry in DEFAULT_CHANNEL_TYPES if not search_term or search_term.lower() in entry.lower()
        ]
        # merge the list, keep the order, and remove duplicates
        return [[name] for name in list(dict.fromkeys(custom_channel_types + default_channel_types))]

    field_definition = LAZY_SESSIONS_FIELDS.get(key)
    if not field_definition:
        return []

    if isinstance(field_definition, StringDatabaseField):
        expr = SESSION_PROPERTY_TO_RAW_SESSIONS_EXPR_MAP.get(key)

        if not expr:
            return []

        if search_term:
            return insight_sync_execute(
                RAW_SELECT_SESSION_PROP_STRING_VALUES_SQL_WITH_FILTER_V3.format(property_expr=expr),
                {"team_id": team.pk, "key": key, "value": "%{}%".format(search_term)},
                query_type="get_session_property_values_with_value",
                team_id=team.pk,
            )
        return insight_sync_execute(
            RAW_SELECT_SESSION_PROP_STRING_VALUES_SQL_V3.format(property_expr=expr),
            {"team_id": team.pk, "key": key},
            query_type="get_session_property_values",
            team_id=team.pk,
        )
    if isinstance(field_definition, BooleanDatabaseField):
        # ideally we'd be able to just send [[True], [False]]
        return [["1"], ["0"]]

    return []
