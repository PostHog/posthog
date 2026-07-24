import re
from typing import TYPE_CHECKING, Optional, cast

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
from posthog.hogql.database.schema.util.where_clause_extractor import (
    SessionMinTimestampWhereClauseExtractorV2,
    build_session_id_v7_pushdown_predicate,
    build_session_property_pre_aggregation_predicate,
)
from posthog.hogql.errors import ResolutionError
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.visitor import clone_expr

from posthog.queries.insight import insight_sync_execute
from posthog.schema_enums import BounceRatePageViewMode, SessionsV2JoinMode

if TYPE_CHECKING:
    from posthog.schema import CustomChannelRule

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
    "id": StringDatabaseField(name="id", description="Session identifier; matches `events.$session_id`."),
    # # TODO remove this, it's a duplicate of the correct session_id field below to get some trends working on a deadline
    "session_id": StringDatabaseField(
        name="session_id", description="Session identifier; matches `events.$session_id`."
    ),
    "session_id_v7": IntegerDatabaseField(name="session_id_v7"),
    "team_id": IntegerDatabaseField(name="team_id"),
    "distinct_id": StringDatabaseField(name="distinct_id"),
    "$start_timestamp": DateTimeDatabaseField(
        name="$start_timestamp", description="Timestamp of the first event in the session."
    ),
    "$end_timestamp": DateTimeDatabaseField(
        name="$end_timestamp", description="Timestamp of the last event in the session."
    ),
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
    requested_fields: dict[str, list[str | int]],
    node: ast.SelectQuery,
    context: HogQLContext,
    extra_where: Optional[ast.Expr] = None,
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
            if name != "session_id_v7":
                group_by_fields.append(ast.Field(chain=cast(list[str | int], [table_name]) + chain))

    where = SessionMinTimestampWhereClauseExtractorV2(context).get_inner_where(node)
    if extra_where is not None:
        where = ast.And(exprs=[where, extra_where]) if where is not None else extra_where

    return ast.SelectQuery(
        select=select_fields,
        select_from=ast.JoinExpr(table=ast.Field(chain=[table_name])),
        group_by=group_by_fields,
        where=where,
    )


def _single_sessions_occurrence_type(node: ast.SelectQuery, lazy_table: "SessionsTableV2") -> Optional[ast.Type]:
    """The resolved type of the query's only ``sessions`` occurrence, or None.

    Returns None when the sessions table appears more than once in the FROM/JOIN
    chain (a self-join — ownership of a ``session_id`` filter is then ambiguous
    because lazy expansion processes occurrences one at a time against the same
    node), or when it cannot be identified. Used to prove a WHERE term belongs to
    the occurrence currently being expanded before pushing it down.
    """
    found: Optional[ast.Type] = None
    join: Optional[ast.JoinExpr] = node.select_from
    while join is not None:
        if isinstance(join.table, ast.Field):
            table_type = join.table.type
            unwrapped = table_type.table_type if isinstance(table_type, ast.TableAliasType) else table_type
            if isinstance(unwrapped, ast.LazyTableType) and unwrapped.table is lazy_table:
                if found is not None:
                    return None
                found = table_type
        join = join.next_join
    return found


def build_direct_session_id_in_pushdown(
    node: ast.SelectQuery, context: HogQLContext, lazy_table: "SessionsTableV2"
) -> Optional[ast.Expr]:
    """Push a top-level ``session_id IN (SELECT …)`` filter below the per-session GROUP BY.

    A direct select over ``sessions`` aggregates every session in the date range
    before outer WHERE filters apply, so an id-set filter (the session-id-set
    pattern: events side first, sessions restricted to matching ids) pays the full
    aggregation anyway. Rewriting it onto ``raw_sessions.session_id_v7`` inside the
    subquery prunes before aggregation — memory and CPU then scale with matching
    sessions, not all sessions. ``GlobalIn`` keeps the id subquery executing once
    on the initiator instead of once per shard. When the rewrite fires, the
    original outer term is neutralized in place (rewritten to ``1 = 1``) so the id
    subquery is not executed a second time above the GROUP BY.

    Exposure: this is keyed on the ``sessionIdPushdown`` modifier, which teams can
    persist in ``team.modifiers`` — so any HogQL query with a matching shape
    (including SQL editor queries) can hit this rewrite, not just the web overview
    runner. That is safe because the rewrite is semantics-preserving: the filter is
    on the GROUP BY key itself, so pruning before aggregation returns the same rows
    as filtering after, string ids are matched only in their canonical (lowercase)
    UUID form exactly like the un-rewritten string comparison, and the rewrite only
    fires when the filtered column provably belongs to this sessions occurrence —
    the query's single one; joined tables' own ``session_id`` columns and sessions
    self-joins are left untouched (locked by the parity and hijack tests in
    test_session_v2_where_clause_extractor.py). Fails open (returns None, outer
    term untouched) on any shape it doesn't recognize — NOT IN, literal lists,
    OR-nested terms, multi-column subqueries — preserving exact original semantics
    there.
    """
    if not context.modifiers or not context.modifiers.sessionIdPushdown:
        return None
    if node.where is None:
        return None
    occurrence_type = _single_sessions_occurrence_type(node, lazy_table)
    if occurrence_type is None:
        return None

    def flatten_and(expr: ast.Expr) -> list[ast.Expr]:
        if isinstance(expr, ast.And):
            return [t for sub in expr.exprs for t in flatten_and(sub)]
        if isinstance(expr, ast.Call) and expr.name == "and":
            return [t for sub in expr.args for t in flatten_and(sub)]
        return [expr]

    for term in flatten_and(node.where):
        if not isinstance(term, ast.CompareOperation) or term.op not in (
            ast.CompareOperationOp.In,
            ast.CompareOperationOp.GlobalIn,
        ):
            continue
        left = term.left.expr if isinstance(term.left, ast.Alias) else term.left
        if (
            not isinstance(left, ast.Field)
            or left.chain[-1] not in ("session_id", "session_id_v7")
            or not isinstance(term.right, ast.SelectQuery)
        ):
            continue
        # Ownership: the field must resolve to THIS sessions occurrence. Chain
        # names alone would also match e.g. `events.properties.session_id`, a
        # replay/warehouse table's own session_id column, or the other side of a
        # sessions self-join — rewriting those would silently drop the user's
        # filter and apply a different one to a different table.
        if not isinstance(left.type, ast.FieldType) or left.type.table_type is not occurrence_type:
            continue

        subquery = cast(ast.SelectQuery, clone_expr(term.right, clear_types=True, clear_locations=True))
        if len(subquery.select) != 1:
            return None
        inner = subquery.select[0]
        if isinstance(inner, ast.Alias):
            alias = inner.alias
        else:
            alias = "session_id_value"
            subquery.select[0] = ast.Alias(alias=alias, expr=inner)

        if left.chain[-1] == "session_id_v7":
            # Already UInt128 — no conversion needed.
            id_expr: ast.Expr = ast.Field(chain=[alias])
        else:
            # String session ids: accurateCastOrNull keeps malformed values from
            # aborting the query (they become NULL and drop out of the set, which
            # matches the join path leaving them unmatched). The toString
            # round-trip keeps only canonical (lowercase) UUID strings: the
            # un-rewritten predicate is a byte-exact string comparison against
            # sessions.session_id (always canonical), so a non-canonical form
            # like an uppercased UUID must not match here either.
            # Two separate cast nodes on purpose — sharing one AST node between
            # parents breaks cloning/resolution assumptions.
            cast_for_check = ast.Call(
                name="accurateCastOrNull", args=[ast.Field(chain=[alias]), ast.Constant(value="UUID")]
            )
            cast_for_value = ast.Call(
                name="accurateCastOrNull", args=[ast.Field(chain=[alias]), ast.Constant(value="UUID")]
            )
            id_expr = ast.Call(
                name="_toUInt128",
                args=[
                    ast.Call(
                        name="if",
                        args=[
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Eq,
                                left=ast.Call(name="toString", args=[cast_for_check]),
                                right=ast.Field(chain=[alias]),
                            ),
                            cast_for_value,
                            ast.Constant(value=None),
                        ],
                    )
                ],
            )

        wrapped = ast.SelectQuery(
            select=[id_expr],
            select_from=ast.JoinExpr(table=subquery),
        )
        # Neutralize the original outer predicate in place: keeping it would make
        # ClickHouse execute the identical GLOBAL IN id-subquery twice (once pushed
        # down, once post-aggregation) — measured as an extra full filtered-events
        # scan per query. The pushed copy below subsumes it exactly.
        term.op = ast.CompareOperationOp.Eq
        term.left = ast.Constant(value=1)
        term.right = ast.Constant(value=1)

        return ast.CompareOperation(
            op=ast.CompareOperationOp.GlobalIn,
            left=ast.Field(chain=["raw_sessions", "session_id_v7"]),
            right=wrapped,
        )
    return None


class SessionsTableV2(LazyTable):
    description: str = (
        "Aggregated user sessions (one row per session), with entry/exit URLs, attribution, and duration. "
        "Join from events via `events.$session_id = sessions.session_id`."
    )
    fields: dict[str, FieldOrTable] = LAZY_SESSIONS_FIELDS

    def lazy_select(
        self,
        table_to_add: LazyTableToAdd,
        context,
        node: ast.SelectQuery,
    ):
        extra_where = build_direct_session_id_in_pushdown(node, context, self)
        return select_from_sessions_table_v2(table_to_add.fields_accessed, node, context, extra_where=extra_where)

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

    extra_where: Optional[ast.Expr] = None
    # Only push down in UUID join mode — the `$session_id` string mode would require wrapping
    # the IN-subquery output in `_toUInt128(toUUID(...))` and isn't needed for the common path.
    if context.modifiers.sessionIdPushdown and context.modifiers.sessionsV2JoinMode == SessionsV2JoinMode.UUID:
        extra_where = build_session_id_v7_pushdown_predicate(
            node,
            join_to_add,
            context,
            session_id_v7_field=ast.Field(chain=["raw_sessions", "session_id_v7"]),
            events_session_id_field=["$session_id_uuid"],
        )

    if context.modifiers.sessionPropertyPreAggregation:
        pre_agg_where = build_session_property_pre_aggregation_predicate(
            node,
            join_to_add,
            context,
            requested_fields=join_to_add.fields_accessed,
            select_from_fn=select_from_sessions_table_v2,
            session_id_v7_field=ast.Field(chain=["raw_sessions", "session_id_v7"]),
        )
        if pre_agg_where is not None:
            extra_where = ast.And(exprs=[extra_where, pre_agg_where]) if extra_where is not None else pre_agg_where

    join_expr = ast.JoinExpr(
        table=select_from_sessions_table_v2(join_to_add.fields_accessed, node, context, extra_where=extra_where)
    )
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

    # lazy import keeps the event-definitions ORM off this module's import path
    from products.event_definitions.backend.models.property_definition import PropertyType  # noqa: PLC0415

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


# NOTE: Keep the AD IDs in sync with `products.web_analytics.backend.hogql_queries.session_attribution_explorer_query_runner.py`
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
    # lazy import keeps the raw-sessions SQL module (Django ORM) off this module's import path
    from posthog.models.raw_sessions.sessions_v2 import (  # noqa: PLC0415
        RAW_SELECT_SESSION_PROP_STRING_VALUES_SQL,
        RAW_SELECT_SESSION_PROP_STRING_VALUES_SQL_WITH_FILTER,
    )

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
