"""SQL for the sessions batch export model."""

import datetime as dt

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from products.batch_exports.backend.temporal.sql.common import BatchExportQuerySettings

# max_inserted_at is only available since around end of 2025. Before
# that, it is the zero value (unix epoch). We use greatest to pick
# $end_timestamp for backfills from before max_inserted_at was available.
SESSIONS_INSERTED_AT_SQL = "greatest(max_inserted_at, $end_timestamp)"

# Lookback days based on the timestamp field of the events that make up a session.
# Sessions is an aggregate table which is not sorted by inserted_at. So, we need
# a filter on $end_timestamp to avoid a full scan of the table. Backfills use
# $end_timestamp rather than max_inserted_at, so this lookback period only applies
# to regular runs. While testing, 3 days catched almost all sessions.
SESSIONS_LOOKBACK_DAYS = dt.timedelta(days=3)

SELECT_FROM_SESSIONS_HOGQL = ast.SelectQuery(
    select=[
        parse_expr("session_id as session_id"),
        parse_expr("toString(session_id_v7) as session_id_v7"),
        parse_expr("team_id"),
        parse_expr("distinct_id as distinct_id"),
        parse_expr("$start_timestamp as start_timestamp"),
        parse_expr("$end_timestamp as end_timestamp"),
        parse_expr("$urls as urls"),
        parse_expr("$num_uniq_urls as num_uniq_urls"),
        parse_expr("$entry_current_url as entry_current_url"),
        parse_expr("$entry_pathname as entry_pathname"),
        parse_expr("$entry_hostname as entry_hostname"),
        parse_expr("$end_current_url as end_current_url"),
        parse_expr("$end_pathname as end_pathname"),
        parse_expr("$end_hostname as end_hostname"),
        parse_expr("$entry_utm_source as entry_utm_source"),
        parse_expr("$entry_utm_campaign as entry_utm_campaign"),
        parse_expr("$entry_utm_medium as entry_utm_medium"),
        parse_expr("$entry_utm_term as entry_utm_term"),
        parse_expr("$entry_utm_content as entry_utm_content"),
        parse_expr("$entry_referring_domain as entry_referring_domain"),
        parse_expr("$entry_gclid as entry_gclid"),
        parse_expr("$entry_fbclid as entry_fbclid"),
        parse_expr("$entry_gad_source as entry_gad_source"),
        parse_expr("$pageview_count as pageview_count"),
        parse_expr("$autocapture_count as autocapture_count"),
        parse_expr("$screen_count as screen_count"),
        parse_expr("$channel_type as channel_type"),
        parse_expr("$session_duration as session_duration"),
        parse_expr("duration as duration"),
        parse_expr("$is_bounce as is_bounce"),
        parse_expr("$last_external_click_url as last_external_click_url"),
        parse_expr("$page_screen_autocapture_count_up_to as page_screen_autocapture_count_up_to"),
        parse_expr("$exit_current_url as exit_current_url"),
        parse_expr("$exit_pathname as exit_pathname"),
        parse_expr("$vitals_lcp as vitals_lcp"),
        # nosemgrep: semgrep.rules.security.hogql-fstring-audit
        parse_expr(f"{SESSIONS_INSERTED_AT_SQL} as _inserted_at"),
        parse_expr("$entry_gclsrc as entry_gclsrc"),
        parse_expr("$entry_dclid as entry_dclid"),
        parse_expr("$entry_gbraid as entry_gbraid"),
        parse_expr("$entry_wbraid as entry_wbraid"),
        parse_expr("$entry_msclkid as entry_msclkid"),
        parse_expr("$entry_twclid as entry_twclid"),
        parse_expr("$entry_li_fat_id as entry_li_fat_id"),
        parse_expr("$entry_mc_cid as entry_mc_cid"),
        parse_expr("$entry_igshid as entry_igshid"),
        parse_expr("$entry_ttclid as entry_ttclid"),
        parse_expr("$entry__kx as entry__kx"),
        parse_expr("$entry_irclid as entry_irclid"),
    ],
    select_from=ast.JoinExpr(table=ast.Field(chain=["sessions"])),
    settings=BatchExportQuerySettings(),
)
