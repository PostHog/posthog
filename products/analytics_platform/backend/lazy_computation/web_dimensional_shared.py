"""Dimensional web precompute pieces shared by more than one product.

`web_bounces_dimensional_preaggregated` is written by web analytics' Dagster job and read by
marketing analytics' attribution reach path. Both must ensure it with an identical insert query and
placeholder set, because the lazy-computation cache key is the query itself, so a divergent copy
computes the same rows again under its own job.

They live here rather than in either product because a product may not import another's internals.
"""

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.models.web_preaggregated.sql import is_eu_cluster

# Forward pad on the per-job event-scan window. The lazy_computation framework
# chunks the precompute span into daily UTC jobs; each job covers
# `[time_window_min, time_window_max)`. A session starting at 23:50 with events
# spilling past midnight would lose its trailing events without a forward pad —
# the HAVING clause attributes the session to its start hour, but the events
# table scan needs to see those trailing events to compute correct per-session
# aggregates. Forward-only is sufficient: the HAVING keeps only sessions whose
# `min(session.$start_timestamp)` falls inside the job window, and every event
# of such a session has `timestamp >= session.$start_timestamp`, so backward
# scanning never picks up anything that survives HAVING.
#
# Sessions longer than 24 h crossing a UTC-day boundary are silently
# undercounted — a documented limitation, not a sizing target (24 h is the
# posthog-js hard cap, covering effectively the whole population).
#
# web analytics has its own copies for its other precompute families. This one belongs to the
# templates below, which cannot import them. The pad is part of the insert query, which is the cache
# key, so a copy that drifts splits the jobs of whoever uses it.
SESSION_FORWARD_PAD_MINUTES = 24 * 60


# TTL tuned for "keep ~90 days warm, don't recompute every time": today's window refreshes hourly,
# the last two days daily, everything older is computed once and held for 90 days. The scheduled job
# re-runs over the rolling window and the framework only recomputes windows whose jobs have expired.
DIMENSIONAL_TTL_SECONDS: dict[str, int] = {
    "0d": 60 * 60,
    "2d": 24 * 60 * 60,
    "default": 90 * 24 * 60 * 60,
}


# Bounces are attributed per session (no pathname dimension). The inner query collapses to one row
# per session and reads the session's computed `$is_bounce` / `$session_duration`; the outer query
# sums them into hourly buckets.
BOUNCES_INSERT_TEMPLATE = """
SELECT
    toStartOfHour(start_timestamp) AS period_bucket,
    host AS host,
    device_type AS device_type,
    entry_pathname AS entry_pathname,
    end_pathname AS end_pathname,
    browser AS browser,
    os AS os,
    viewport_width AS viewport_width,
    viewport_height AS viewport_height,
    referring_domain AS referring_domain,
    utm_source AS utm_source,
    utm_medium AS utm_medium,
    utm_campaign AS utm_campaign,
    utm_term AS utm_term,
    utm_content AS utm_content,
    country_code AS country_code,
    city_name AS city_name,
    region_code AS region_code,
    region_name AS region_name,
    has_gclid AS has_gclid,
    has_gad_source_paid_search AS has_gad_source_paid_search,
    has_fbclid AS has_fbclid,
    mat_metadata_backend AS mat_metadata_backend,
    mat_metadata_loggedIn AS mat_metadata_loggedIn,
    uniqState(session_person_id) AS persons_uniq_state,
    uniqState(session_id) AS sessions_uniq_state,
    sumState(pageview_count) AS pageviews_count_state,
    sumState(assumeNotNull(toInt(ifNull(is_bounce, 0)))) AS bounces_count_state,
    sumState(session_duration) AS total_session_duration_state,
    sumState(assumeNotNull(toInt(1))) AS total_session_count_state
FROM (
    SELECT
        any(events.person_id) AS session_person_id,
        events.$session_id AS session_id,
        min(session.$start_timestamp) AS start_timestamp,
        any(events.properties.$host) AS host,
        any(events.properties.$device_type) AS device_type,
        any(events.properties.$browser) AS browser,
        any(events.properties.$os) AS os,
        toIntOrZero(toString(any(events.properties.$viewport_width))) AS viewport_width,
        toIntOrZero(toString(any(events.properties.$viewport_height))) AS viewport_height,
        any(events.properties.$geoip_country_code) AS country_code,
        any(events.properties.$geoip_city_name) AS city_name,
        any(events.properties.$geoip_subdivision_1_code) AS region_code,
        any(events.properties.$geoip_subdivision_1_name) AS region_name,
        any(session.$entry_pathname) AS entry_pathname,
        any(session.$end_pathname) AS end_pathname,
        any(session.$entry_referring_domain) AS referring_domain,
        any(session.$entry_utm_source) AS utm_source,
        any(session.$entry_utm_medium) AS utm_medium,
        any(session.$entry_utm_campaign) AS utm_campaign,
        any(session.$entry_utm_term) AS utm_term,
        any(session.$entry_utm_content) AS utm_content,
        any(and(notEmpty(coalesce(session.$entry_gclid, '')), notEquals(coalesce(session.$entry_gclid, ''), 'null'))) AS has_gclid,
        any(equals(coalesce(session.$entry_gad_source, ''), '1')) AS has_gad_source_paid_search,
        any(and(notEmpty(coalesce(session.$entry_fbclid, '')), notEquals(coalesce(session.$entry_fbclid, ''), 'null'))) AS has_fbclid,
        {mat_logged_in_inner} AS mat_metadata_loggedIn,
        {mat_backend_inner} AS mat_metadata_backend,
        any(session.$is_bounce) AS is_bounce,
        assumeNotNull(toInt(any(session.$session_duration))) AS session_duration,
        assumeNotNull(toInt(countIf(or(equals(events.event, '$pageview'), equals(events.event, '$screen'))))) AS pageview_count
    FROM events
    WHERE and(
        events.$session_id IS NOT NULL,
        or(equals(events.event, '$pageview'), equals(events.event, '$screen')),
        events.timestamp >= {time_window_min},
        events.timestamp < ({time_window_max} + toIntervalMinute({pad_minutes}))
    )
    GROUP BY session_id
    HAVING and(
        toStartOfHour(min(session.$start_timestamp)) >= {time_window_min},
        toStartOfHour(min(session.$start_timestamp)) < {time_window_max}
    )
)
GROUP BY
    period_bucket,
    host,
    device_type,
    entry_pathname,
    end_pathname,
    browser,
    os,
    viewport_width,
    viewport_height,
    referring_domain,
    utm_source,
    utm_medium,
    utm_campaign,
    utm_term,
    utm_content,
    country_code,
    city_name,
    region_code,
    region_name,
    has_gclid,
    has_gad_source_paid_search,
    has_fbclid,
    mat_metadata_backend,
    mat_metadata_loggedIn
"""


def _mat_metadata_placeholders() -> dict[str, ast.Expr]:
    """Build the EU/US `mat_metadata_*` placeholder expressions.

    On EU the custom metadata is a materialized event property, aggregated per
    session-group with `any()` (mirroring v2). On US these columns are always
    NULL, typed so the INSERT into the Nullable columns succeeds.
    """
    if not is_eu_cluster():
        # Typed NULLs without a CAST (HogQL rejects `CAST(NULL AS Nullable(...))`):
        # `if(false, <typed literal>, NULL)` yields Nullable(Bool)/Nullable(String).
        return {
            "mat_logged_in_inner": parse_expr("if(1 = 0, true, NULL)"),
            "mat_backend_inner": parse_expr("if(1 = 0, '', NULL)"),
        }

    return {
        "mat_logged_in_inner": parse_expr(
            "any(if(events.properties.`metadata.loggedIn` IS NULL, NULL, equals(events.properties.`metadata.loggedIn`, 'true')))"
        ),
        "mat_backend_inner": parse_expr("any(events.properties.`metadata.backend`)"),
    }


def base_placeholders() -> dict[str, ast.Expr]:
    """Placeholders every dimensional INSERT needs.

    Public because marketing analytics' attribution reach path ensures the same bounces table and must
    pass an identical insert query, because the lazy-computation cache key is the query, so a different
    placeholder set would compute a second, redundant copy of the same rows under its own job.
    """
    return {
        "pad_minutes": ast.Constant(value=SESSION_FORWARD_PAD_MINUTES),
        **_mat_metadata_placeholders(),
    }
