import re
from typing import TYPE_CHECKING, Optional, cast

from posthog.schema import BounceRatePageViewMode, CustomChannelRule, SessionsV2JoinMode

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
)
from posthog.hogql.database.schema.channel_type import DEFAULT_CHANNEL_TYPES, ChannelTypeExprs, create_channel_type_expr
from posthog.hogql.database.schema.sessions_v1 import DEFAULT_BOUNCE_RATE_DURATION_SECONDS, null_if_empty
from posthog.hogql.database.schema.util.where_clause_extractor import SessionMinTimestampWhereClauseExtractorV2
from posthog.hogql.errors import ResolutionError
from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.models.property_definition import PropertyType
from posthog.models.raw_sessions.sql import (
    RAW_SELECT_SESSION_PROP_STRING_VALUES_SQL,
    RAW_SELECT_SESSION_PROP_STRING_VALUES_SQL_WITH_FILTER,
)
from posthog.queries.insight import insight_sync_execute

if TYPE_CHECKING:
    from posthog.models.team import Team

RAW_SESSIONS_FIELDS: dict[str, FieldOrTable] = {
    "session_id_v7": IntegerDatabaseField(name="session_id_v7", nullable=False),
    "team_id": IntegerDatabaseField(name="team_id", nullable=False),
    "distinct_id": StringDatabaseField(name="distinct_id", nullable=False),
    "min_timestamp": DateTimeDatabaseField(name="min_timestamp", nullable=False),
    "max_timestamp": DateTimeDatabaseField(name="max_timestamp", nullable=False),
    "max_inserted_at": DateTimeDatabaseField(name="max_inserted_at", nullable=False),
    "urls": StringArrayDatabaseField(name="urls", nullable=False),
    # many of the fields in the raw tables are AggregateFunction state, rather than simple types
    "entry_url": DatabaseField(name="entry_url", nullable=False),
    "end_url": DatabaseField(name="end_url", nullable=False),
    "initial_referring_domain": DatabaseField(name="initial_referring_domain", nullable=False),
    # UTM parameters
    "initial_utm_source": DatabaseField(name="initial_utm_source", nullable=False),
    "initial_utm_campaign": DatabaseField(name="initial_utm_campaign", nullable=False),
    "initial_utm_medium": DatabaseField(name="initial_utm_medium", nullable=False),
    "initial_utm_term": DatabaseField(name="initial_utm_term", nullable=False),
    "initial_utm_content": DatabaseField(name="initial_utm_content", nullable=False),
    # Other Ad / campaign / attribution IDs
    "initial_gclid": DatabaseField(name="initial_gclid", nullable=False),
    "initial_gad_source": DatabaseField(name="initial_gad_source", nullable=False),
    "initial_gclsrc": DatabaseField(name="initial_gclsrc", nullable=False),
    "initial_dclid": DatabaseField(name="initial_dclid", nullable=False),
    "initial_gbraid": DatabaseField(name="initial_gbraid", nullable=False),
    "initial_wbraid": DatabaseField(name="initial_wbraid", nullable=False),
    "initial_fbclid": DatabaseField(name="initial_fbclid", nullable=False),
    "initial_msclkid": DatabaseField(name="initial_msclkid", nullable=False),
    "initial_twclid": DatabaseField(name="initial_twclid", nullable=False),
    "initial_li_fat_id": DatabaseField(name="initial_li_fat_id", nullable=False),
    "initial_mc_cid": DatabaseField(name="initial_mc_cid", nullable=False),
    "initial_igshid": DatabaseField(name="initial_igshid", nullable=False),
    "initial_ttclid": DatabaseField(name="initial_ttclid", nullable=False),
    "initial__kx": DatabaseField(name="initial__kx", nullable=False),
    "initial_irclid": DatabaseField(name="initial_irclid", nullable=False),
    # do not expose the count fields, as we can't rely on them being accurate due to double-counting events
    "pageview_uniq": DatabaseField(name="pageview_uniq", nullable=True),
    "autocapture_uniq": DatabaseField(name="autocapture_uniq", nullable=True),
    "screen_uniq": DatabaseField(name="screen_uniq", nullable=True),
    "last_external_click_url": StringDatabaseField(name="last_external_click_url", nullable=False),
    "page_screen_autocapture_uniq_up_to": DatabaseField(name="page_screen_autocapture_uniq_up_to", nullable=True),
    "vitals_lcp": DatabaseField(name="vitals_lcp", nullable=True),
}

LAZY_SESSIONS_FIELDS: dict[str, FieldOrTable] = {
    "id": StringDatabaseField(name="id"),
    # # TODO remove this, it's a duplicate of the correct session_id field below to get some trends working on a deadline
    "session_id": StringDatabaseField(name="session_id"),
    "session_id_v7": IntegerDatabaseField(name="session_id_v7"),
    "team_id": IntegerDatabaseField(name="team_id"),
    "distinct_id": StringDatabaseField(name="distinct_id"),
    "$start_timestamp": DateTimeDatabaseField(name="$start_timestamp"),
    "$end_timestamp": DateTimeDatabaseField(name="$end_timestamp"),
    "max_inserted_at": DateTimeDatabaseField(name="max_inserted_at"),
    "$urls": StringArrayDatabaseField(name="$urls"),
    "$num_uniq_urls": IntegerDatabaseField(name="$num_uniq_urls"),
    "$entry_current_url": StringDatabaseField(name="$entry_current_url"),
    "$entry_pathname": StringDatabaseField(name="$entry_pathname"),
    "$entry_hostname": StringDatabaseField(name="$entry_host"),
    "$end_current_url": StringDatabaseField(name="$end_current_url"),
    "$end_pathname": StringDatabaseField(name="$end_pathname"),
    "$end_hostname": StringDatabaseField(name="$end_hostname"),
    "$entry_referring_domain": StringDatabaseField(name="$entry_referring_domain"),
    # UTM parameters
    "$entry_utm_source": StringDatabaseField(name="$entry_utm_source"),
    "$entry_utm_campaign": StringDatabaseField(name="$entry_utm_campaign"),
    "$entry_utm_medium": StringDatabaseField(name="$entry_utm_medium"),
    "$entry_utm_term": StringDatabaseField(name="$entry_utm_term"),
    "$entry_utm_content": StringDatabaseField(name="$entry_utm_content"),
    # Other Ad / campaign / attribution IDs
    "$entry_gclid": StringDatabaseField(name="$entry_gclid"),
    "$entry_gad_source": StringDatabaseField(name="$entry_gad_source"),
    "$entry_gclsrc": StringDatabaseField(name="$entry_gclsrc"),
    "$entry_dclid": StringDatabaseField(name="$entry_dclid"),
    "$entry_gbraid": StringDatabaseField(name="$entry_gbraid"),
    "$entry_wbraid": StringDatabaseField(name="$entry_wbraid"),
    "$entry_fbclid": StringDatabaseField(name="$entry_fbclid"),
    "$entry_msclkid": StringDatabaseField(name="$entry_msclkid"),
    "$entry_twclid": StringDatabaseField(name="$entry_twclid"),
    "$entry_li_fat_id": StringDatabaseField(name="$entry_li_fat_id"),
    "$entry_mc_cid": StringDatabaseField(name="$entry_mc_cid"),
    "$entry_igshid": StringDatabaseField(name="$entry_igshid"),
    "$entry_ttclid": StringDatabaseField(name="$entry_ttclid"),
    "$entry__kx": StringDatabaseField(name="$entry__kx"),
    "$entry_irclid": StringDatabaseField(name="$entry_irclid"),
    # we expose "count" fields here, though they are actually the aggregates of the uniq columns in the raw tables
    "$pageview_count": IntegerDatabaseField(name="$pageview_count"),
    "$autocapture_count": IntegerDatabaseField(name="$autocapture_count"),
    "$screen_count": IntegerDatabaseField(name="$screen_count"),
    "$channel_type": StringDatabaseField(name="$channel_type"),
    "$session_duration": IntegerDatabaseField(name="$session_duration"),
    "duration": IntegerDatabaseField(
        name="duration"
    ),  # alias of $session_duration, deprecated but included for backwards compatibility
    "$is_bounce": BooleanDatabaseField(name="$is_bounce"),
    "$last_external_click_url": StringDatabaseField(name="$last_external_click_url"),
    "$page_screen_autocapture_count_up_to": DatabaseField(name="$$page_screen_autocapture_count_up_to"),
    # some aliases for people upgrading from v1 to v2
    "$exit_current_url": StringDatabaseField(name="$exit_current_url"),
    "$exit_pathname": StringDatabaseField(name="$exit_pathname"),
    "$vitals_lcp": FloatDatabaseField(name="vitals_lcp", nullable=True),
}


class RawSessionsTableV2(Table):
    fields: dict[str, FieldOrTable] = RAW_SESSIONS_FIELDS

    def to_printed_clickhouse(self, context):
        return "raw_sessions"

    def to_printed_hogql(self):
        return "raw_sessions"

    def avoid_asterisk_fields(self) -> list[str]:
        return [
            "session_id_v7",  # HogQL insights currently don't support returning uint128s due to json serialisation
            # our clickhouse driver can't return aggregate states
            "distinct_id",
            "entry_url",
            "end_url",
            "initial_utm_source",
            "initial_utm_campaign",
            "initial_utm_medium",
            "initial_utm_term",
            "initial_utm_content",
            "initial_referring_domain",
            "initial_gclid",
            "initial_gad_source",
            "initial_gclsrc",
            "initial_dclid",
            "initial_gbraid",
            "initial_wbraid",
            "initial_fbclid",
            "initial_msclkid",
            "initial_twclid",
            "initial_li_fat_id",
            "initial_mc_cid",
            "initial_igshid",
            "initial_ttclid",
            "initial__kx",
            "initial_irclid",
            "pageview_uniq",
            "autocapture_uniq",
            "screen_uniq",
            "last_external_click_url",
            "page_screen_autocapture_uniq_up_to",
            "vitals_lcp",
        ]


def select_from_sessions_table_v2(
    requested_fields: dict[str, list[str | int]], node: ast.SelectQuery, context: HogQLContext
):
    from posthog.hogql import ast

    table_name = "raw_sessions"

    # Always include "session_id", as it's the key we use to make further joins, and it'd be great if it's available
    if "session_id_v7" not in requested_fields:
        requested_fields = {**requested_fields, "session_id_v7": ["session_id_v7"]}

    def arg_min_merge_field(field_name: str) -> ast.Call:
        return ast.Call(
            name="nullIf",
            args=[
                ast.Call(name="argMinMerge", args=[ast.Field(chain=[table_name, field_name])]),
                ast.Constant(value="null"),
            ],
        )

    def arg_max_merge_field(field_name: str) -> ast.Call:
        return ast.Call(
            name="nullIf",
            args=[
                ast.Call(name="argMaxMerge", args=[ast.Field(chain=[table_name, field_name])]),
                ast.Constant(value="null"),
            ],
        )

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
        "$entry_current_url": null_if_empty(arg_min_merge_field("entry_url")),
        "$end_current_url": null_if_empty(arg_max_merge_field("end_url")),
        "$entry_utm_source": null_if_empty(arg_min_merge_field("initial_utm_source")),
        "$entry_utm_campaign": null_if_empty(arg_min_merge_field("initial_utm_campaign")),
        "$entry_utm_medium": null_if_empty(arg_min_merge_field("initial_utm_medium")),
        "$entry_utm_term": null_if_empty(arg_min_merge_field("initial_utm_term")),
        "$entry_utm_content": null_if_empty(arg_min_merge_field("initial_utm_content")),
        "$entry_referring_domain": null_if_empty(arg_min_merge_field("initial_referring_domain")),
        "$entry_gclid": null_if_empty(arg_min_merge_field("initial_gclid")),
        "$entry_gad_source": null_if_empty(arg_min_merge_field("initial_gad_source")),
        "$entry_gclsrc": null_if_empty(arg_min_merge_field("initial_gclsrc")),
        "$entry_dclid": null_if_empty(arg_min_merge_field("initial_dclid")),
        "$entry_gbraid": null_if_empty(arg_min_merge_field("initial_gbraid")),
        "$entry_wbraid": null_if_empty(arg_min_merge_field("initial_wbraid")),
        "$entry_fbclid": null_if_empty(arg_min_merge_field("initial_fbclid")),
        "$entry_msclkid": null_if_empty(arg_min_merge_field("initial_msclkid")),
        "$entry_twclid": null_if_empty(arg_min_merge_field("initial_twclid")),
        "$entry_li_fat_id": null_if_empty(arg_min_merge_field("initial_li_fat_id")),
        "$entry_mc_cid": null_if_empty(arg_min_merge_field("initial_mc_cid")),
        "$entry_igshid": null_if_empty(arg_min_merge_field("initial_igshid")),
        "$entry_ttclid": null_if_empty(arg_min_merge_field("initial_ttclid")),
        "$entry__kx": null_if_empty(arg_min_merge_field("initial__kx")),
        "$entry_irclid": null_if_empty(arg_min_merge_field("initial_irclid")),
        # the count columns here do not come from the "count" columns in the raw table, instead aggregate the uniq columns
        "$pageview_count": ast.Call(name="uniqMerge", args=[ast.Field(chain=[table_name, "pageview_uniq"])]),
        "$screen_count": ast.Call(name="uniqMerge", args=[ast.Field(chain=[table_name, "screen_uniq"])]),
        "$autocapture_count": ast.Call(name="uniqMerge", args=[ast.Field(chain=[table_name, "autocapture_uniq"])]),
        "$last_external_click_url": null_if_empty(arg_max_merge_field("last_external_click_url")),
        "$page_screen_autocapture_count_up_to": ast.Call(
            name="uniqUpToMerge",
            params=[ast.Constant(value=1)],
            args=[ast.Field(chain=[table_name, "page_screen_autocapture_uniq_up_to"])],
        ),
        "$vitals_lcp": ast.Call(name="argMinMerge", args=[ast.Field(chain=[table_name, "vitals_lcp"])]),
    }
    # Alias
    aggregate_fields["id"] = aggregate_fields["session_id"]
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
    if context.modifiers.bounceRatePageViewMode == BounceRatePageViewMode.UNIQ_PAGE_SCREEN_AUTOCAPTURES:
        bounce_event_count = aggregate_fields["$page_screen_autocapture_count_up_to"]
        aggregate_fields["$is_bounce"] = ast.Call(
            name="if",
            args=[
                # if the count is 0, return NULL, so it doesn't contribute towards the bounce rate either way
                ast.Call(name="equals", args=[bounce_event_count, ast.Constant(value=0)]),
                ast.Constant(value=None),
                ast.Call(
                    name="not",
                    args=[
                        ast.Call(
                            name="or",
                            args=[
                                # if pageviews + autocaptures > 1, not a bounce
                                ast.Call(name="greater", args=[bounce_event_count, ast.Constant(value=1)]),
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
    else:
        bounce_pageview_count = aggregate_fields["$pageview_count"]
        aggregate_fields["$is_bounce"] = ast.Call(
            name="if",
            args=[
                # if pageview_count is 0, return NULL so it doesn't contribute towards the bounce rate either way
                ast.Call(name="equals", args=[bounce_pageview_count, ast.Constant(value=0)]),
                ast.Constant(value=None),
                ast.Call(
                    name="not",
                    args=[
                        ast.Call(
                            name="or",
                            args=[
                                # if > 1 pageview, not a bounce
                                ast.Call(name="greater", args=[bounce_pageview_count, ast.Constant(value=1)]),
                                # if > 0 autocapture events, not a bounce
                                ast.Call(
                                    name="greater", args=[aggregate_fields["$autocapture_count"], ast.Constant(value=0)]
                                ),
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
    aggregate_fields["$channel_type"] = create_channel_type_expr(
        context.modifiers.customChannelTypeRules,
        ChannelTypeExprs(
            campaign=aggregate_fields["$entry_utm_campaign"],
            medium=aggregate_fields["$entry_utm_medium"],
            source=aggregate_fields["$entry_utm_source"],
            url=aggregate_fields["$entry_current_url"],
            hostname=aggregate_fields["$entry_hostname"],
            pathname=aggregate_fields["$entry_pathname"],
            referring_domain=aggregate_fields["$entry_referring_domain"],
            has_gclid=ast.Call(
                name="isNotNull",
                args=[aggregate_fields["$entry_gclid"]],
            ),
            has_fbclid=ast.Call(
                name="isNotNull",
                args=[aggregate_fields["$entry_fbclid"]],
            ),
            gad_source=aggregate_fields["$entry_gad_source"],
        ),
        timings=context.timings,
    )
    # some aliases for people upgrading from v1 to v2
    aggregate_fields["$exit_current_url"] = aggregate_fields["$end_current_url"]
    aggregate_fields["$exit_pathname"] = aggregate_fields["$end_pathname"]

    select_fields: list[ast.Expr] = []
    group_by_fields: list[ast.Expr] = [ast.Field(chain=[table_name, "session_id_v7"])]

    for name, chain in requested_fields.items():
        if name in aggregate_fields:
            select_fields.append(ast.Alias(alias=name, expr=aggregate_fields[name]))
        else:
            select_fields.append(
                ast.Alias(alias=name, expr=ast.Field(chain=cast(list[str | int], [table_name]) + chain))
            )
            group_by_fields.append(ast.Field(chain=cast(list[str | int], [table_name]) + chain))

    where = SessionMinTimestampWhereClauseExtractorV2(context).get_inner_where(node)

    return ast.SelectQuery(
        select=select_fields,
        select_from=ast.JoinExpr(table=ast.Field(chain=[table_name])),
        group_by=group_by_fields,
        where=where,
    )


class SessionsTableV2(LazyTable):
    fields: dict[str, FieldOrTable] = LAZY_SESSIONS_FIELDS

    def lazy_select(
        self,
        table_to_add: LazyTableToAdd,
        context,
        node: ast.SelectQuery,
    ):
        return select_from_sessions_table_v2(table_to_add.fields_accessed, node, context)

    def to_printed_clickhouse(self, context):
        return "sessions"

    def to_printed_hogql(self):
        return "sessions"

    def avoid_asterisk_fields(self) -> list[str]:
        return [
            "session_id_v7",  # HogQL insights currently don't support returning uint128s due to json serialisation
            "id",  # prefer to use session_id
            "duration",  # alias of $session_duration, deprecated but included for backwards compatibility
            # aliases for people upgrading from v1 to v2
            "$exit_current_url",
            "$exit_pathname",
        ]


def session_id_to_session_id_v7_as_uint128_expr(session_id: ast.Expr) -> ast.Expr:
    return ast.Call(
        name="_toUInt128",
        args=[ast.Call(name="toUUID", args=[session_id])],
    )


def join_events_table_to_sessions_table_v2(
    join_to_add: LazyJoinToAdd, context: HogQLContext, node: ast.SelectQuery
) -> ast.JoinExpr:
    from posthog.hogql import ast

    if not join_to_add.fields_accessed:
        raise ResolutionError("No fields requested from events")

    join_expr = ast.JoinExpr(table=select_from_sessions_table_v2(join_to_add.fields_accessed, node, context))
    join_expr.join_type = "LEFT JOIN"
    join_expr.alias = join_to_add.to_table
    if context.modifiers.sessionsV2JoinMode == SessionsV2JoinMode.UUID:
        join_expr.constraint = ast.JoinConstraint(
            expr=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=[join_to_add.from_table, "$session_id_uuid"]),
                right=ast.Field(chain=[join_to_add.to_table, "session_id_v7"]),
            ),
            constraint_type="ON",
        )
    else:
        join_expr.constraint = ast.JoinConstraint(
            expr=ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=session_id_to_session_id_v7_as_uint128_expr(
                    ast.Field(chain=[join_to_add.from_table, "$session_id"])
                ),
                right=ast.Field(chain=[join_to_add.to_table, "session_id_v7"]),
            ),
            constraint_type="ON",
        )
    return join_expr


def get_lazy_session_table_properties_v2(search: Optional[str]):
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
        # aliases for people upgrading from v1 to v2
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
    "$entry_referring_domain": "finalizeAggregation(initial_referring_domain)",
    "$entry_utm_source": "finalizeAggregation(initial_utm_source)",
    "$entry_utm_campaign": "finalizeAggregation(initial_utm_campaign)",
    "$entry_utm_medium": "finalizeAggregation(initial_utm_medium)",
    "$entry_utm_term": "finalizeAggregation(initial_utm_term)",
    "$entry_utm_content": "finalizeAggregation(initial_utm_content)",
    "$entry_gclid": "finalizeAggregation(initial_gclid)",
    "$entry_gad_source": "finalizeAggregation(initial_gad_source)",
    "$entry_gclsrc": "finalizeAggregation(initial_gclsrc)",
    "$entry_dclid": "finalizeAggregation(initial_dclid)",
    "$entry_gbraid": "finalizeAggregation(initial_gbraid)",
    "$entry_wbraid": "finalizeAggregation(initial_wbraid)",
    "$entry_fbclid": "finalizeAggregation(initial_fbclid)",
    "$entry_msclkid": "finalizeAggregation(initial_msclkid)",
    "$entry_twclid": "finalizeAggregation(initial_twclid)",
    "$entry_li_fat_id": "finalizeAggregation(initial_li_fat_id)",
    "$entry_mc_cid": "finalizeAggregation(initial_mc_cid)",
    "$entry_igshid": "finalizeAggregation(initial_igshid)",
    "$entry_ttclid": "finalizeAggregation(initial_ttclid)",
    "$entry__kx": "finalizeAggregation(initial__kx)",
    "$entry_irclid": "finalizeAggregation(initial_irclid)",
    "$entry_pathname": "path(finalizeAggregation(entry_url))",
    "$entry_current_url": "finalizeAggregation(entry_url)",
    "$end_current_url": "finalizeAggregation(end_url)",
    "$end_pathname": "path(finalizeAggregation(end_url))",
    "$last_external_click_url": "finalizeAggregation(last_external_click_url)",
    "$vitals_lcp": "finalizeAggregation(vitals_lcp)",
}


def get_lazy_session_table_values_v2(key: str, search_term: Optional[str], team: "Team"):
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
                RAW_SELECT_SESSION_PROP_STRING_VALUES_SQL_WITH_FILTER.format(property_expr=expr),
                {"team_id": team.pk, "key": key, "value": "%{}%".format(search_term)},
                query_type="get_session_property_values_with_value",
                team_id=team.pk,
            )
        return insight_sync_execute(
            RAW_SELECT_SESSION_PROP_STRING_VALUES_SQL.format(property_expr=expr),
            {"team_id": team.pk, "key": key},
            query_type="get_session_property_values",
            team_id=team.pk,
        )
    if isinstance(field_definition, BooleanDatabaseField):
        # ideally we'd be able to just send [[True], [False]]
        return [["1"], ["0"]]

    return []
