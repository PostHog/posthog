"""SQL eval cases for the sandboxed coding agent.

Intent mirrors ``ee/hogai/eval/ci/eval_sql.py`` — the CI version drives the
LangGraph chat agent in ``AgentMode.SQL`` (which forces the SQL path), this
version exercises the same questions end-to-end through the sandboxed agent
+ PostHog MCP tools and judges the HogQL the agent ran via the
``execute-sql`` MCP tool.

Prompts are rephrased from the CI dataset to explicitly request HogQL.
The CI flow forces SQL via ``AgentMode.SQL``; the sandboxed agent has no
equivalent mode and is free to answer with typed query tools
(``query-trends`` / ``query-funnel`` / ``query-retention``). Without the
``Write a HogQL query that…`` framing, several cases would route to a
typed query tool — perfectly valid for the user, but not what this eval
is testing. The framing is the forcing function in lieu of an agent mode.

To run:
    pytest ee/hogai/eval/sandboxed/sql/eval_sql.py
"""

from __future__ import annotations

import pytest

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.product_analytics.scorers import INSIGHT_WRITE_TOOLS
from ee.hogai.eval.sandboxed.retrieval.scorers import SkillLoaded
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero, LastToolCallNot, NoToolCall, RequiredToolCall
from ee.hogai.eval.sandboxed.sql.scorers import SQLSchemaAlignment


def _sql_case(*, name: str, prompt: str, expected_sql: str) -> SandboxedEvalCase:
    return SandboxedEvalCase(
        name=name,
        prompt=prompt,
        expected={"sql_query": expected_sql.strip()},
    )


@pytest.mark.django_db
async def eval_sql(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    cases = [
        # Straightforward breakdowns
        _sql_case(
            name="sql_pageviews_by_browser",
            prompt="Write a HogQL query that counts pageviews grouped by browser, ordered by count descending.",
            expected_sql="""
SELECT properties.$browser as browser, count(*) as pageview_count
FROM events
WHERE event = '$pageview'
GROUP BY browser
ORDER BY pageview_count DESC
LIMIT 100
""",
        ),
        _sql_case(
            name="sql_top_countries_by_users_7d",
            prompt="Write a HogQL query that returns the top 10 countries by number of unique users in the last 7 days.",
            expected_sql="""
SELECT properties.$geoip_country_name as country, count(distinct person_id) as user_count
FROM events
WHERE timestamp >= now() - interval 7 day
GROUP BY country
ORDER BY user_count DESC
LIMIT 10
""",
        ),
        # Session duration
        _sql_case(
            name="sql_avg_session_duration_by_dow",
            prompt="Using HogQL, give me the average session duration broken down by day of week.",
            expected_sql="""
SELECT toDayOfWeek(timestamp) as day_of_week,
       avg(session.$session_duration) as avg_session_duration
FROM events
GROUP BY day_of_week
ORDER BY day_of_week
""",
        ),
        _sql_case(
            name="sql_pricing_to_purchase_pct_this_month",
            prompt=(
                "Write a HogQL query that returns what percentage of users who visited the pricing page "
                "made a purchase in this month."
            ),
            expected_sql="""
WITH pricing_visitors AS (
    SELECT distinct person_id
    FROM events
    WHERE event = 'viewed_pricing_page'
    AND date_trunc('month', timestamp) = date_trunc('month', now())
),
purchasers AS (
    SELECT distinct person_id
    FROM events
    WHERE event = 'purchase'
    AND date_trunc('month', timestamp) = date_trunc('month', now())
)
SELECT
    count(DISTINCT pv.person_id) AS pricing_visitors_count,
    count(DISTINCT p.person_id) AS purchasers_count,
    (count(DISTINCT p.person_id) * 100.0 / nullIf(count(DISTINCT pv.person_id), 0)) AS conversion_percentage
FROM pricing_visitors pv
LEFT JOIN purchasers p ON pv.person_id = p.person_id
""",
        ),
        # Conversion (ordered)
        _sql_case(
            name="sql_onboarding_flow_in_sequence",
            prompt=(
                "Write a HogQL query that counts how many users completed the onboarding flow "
                "(viewed welcome page, created profile, and completed tutorial) in that sequence."
            ),
            expected_sql="""
WITH occurences AS (
    SELECT
        person_id,
        event,
        timestamp,
        ROW_NUMBER() OVER (PARTITION BY person_id, event ORDER BY timestamp) as occurrence
    FROM events
    WHERE event IN ('viewed_welcome_page', 'created_profile', 'completed_tutorial')
),
user_funnel AS (
    SELECT
        person_id,
        maxIf(timestamp, event = 'viewed_welcome_page') as welcome_time,
        maxIf(timestamp, event = 'created_profile') as profile_time,
        maxIf(timestamp, event = 'completed_tutorial') as tutorial_time
    FROM occurences
    WHERE occurrence = 1
    GROUP BY person_id
    HAVING count(distinct event) = 3
)
SELECT count(*) as users_completed_onboarding
FROM user_funnel
WHERE welcome_time < profile_time AND profile_time < tutorial_time
""",
        ),
        # Conversion (unordered)
        _sql_case(
            name="sql_onboarding_flow_any_order",
            prompt=(
                "Write a HogQL query that counts how many users completed the onboarding flow "
                "(viewed welcome page, created profile, and completed tutorial) regardless of sequence."
            ),
            expected_sql="""
WITH occurences AS (
    SELECT person_id, event
    FROM events
    WHERE event IN ('viewed_welcome_page', 'created_profile', 'completed_tutorial')
),
user_funnel AS (
    SELECT
        person_id,
        count(distinct event) as event_count
    FROM occurences
    GROUP BY person_id
)
SELECT count(*) as users_completed_onboarding
FROM user_funnel
WHERE event_count = 3
""",
        ),
        # Property math
        _sql_case(
            name="sql_distinct_browsers_per_day_14d",
            prompt=(
                "Using HogQL, give me the number of distinct values of property $browser seen "
                "in each of the last 14 days."
            ),
            expected_sql="""
SELECT date_trunc('day', timestamp) as day, count(distinct properties.$browser) as distinct_browser_count
FROM events
WHERE event = '$pageview'
  AND timestamp >= now() - INTERVAL 14 DAY
GROUP BY day
ORDER BY day
""",
        ),
        _sql_case(
            name="sql_paid_bill_total_hedgebox_30d",
            prompt=(
                "Write a HogQL query that sums up the total amounts paid for the 'paid_bill' event "
                "over the past month for Hedgebox Inc."
            ),
            expected_sql="""
SELECT sum(toFloat(properties.amount_usd)) AS total_amount_paid
FROM events
WHERE event = 'paid_bill'
  AND timestamp >= now() - INTERVAL 30 DAY
  AND organization.properties.name = 'Hedgebox Inc.'
""",
        ),
        # Open questions to list persons
        _sql_case(
            name="sql_5_users_to_interview_file_downloads",
            prompt=(
                "Write a HogQL query that returns the 5 users I should interview around file download usage, "
                "with their email and name."
            ),
            expected_sql="""
SELECT
    person_id,
    person.properties.email as email,
    person.properties.name as name,
    count(*) as usage_count,
    max(timestamp) as last_used
FROM events
WHERE event = 'downloaded_file'
GROUP BY person_id, person.properties.email, person.properties.name
ORDER BY usage_count DESC, last_used DESC
LIMIT 5
""",
        ),
        _sql_case(
            name="sql_top_5_file_downloaders_recent",
            prompt=(
                "Write a HogQL query that returns the 5 users that have downloaded the most files in the past few weeks, "
                "with their email and name."
            ),
            expected_sql="""
SELECT
    person_id,
    person.properties.email as email,
    person.properties.name as name,
    count(*) as file_download_count,
    max(timestamp) as last_download
FROM events
WHERE event = 'downloaded_file'
    AND timestamp >= now() - INTERVAL 14 DAY
GROUP BY person_id, person.properties.email, person.properties.name
ORDER BY file_download_count DESC
LIMIT 5
""",
        ),
        _sql_case(
            name="sql_10_file_downloader_profiles",
            prompt=(
                "Using HogQL, show me 10 example person profiles of file download users, including email, name, "
                "company, role, created_at, and number of downloads."
            ),
            expected_sql="""
SELECT DISTINCT
    person_id,
    person.properties.email as email,
    person.properties.name as name,
    person.properties.company as company,
    person.properties.role as role,
    person.properties.created_at as user_created_at,
    count(*) as file_download_event_count
FROM events
WHERE event = 'downloaded_file'
GROUP BY person_id, person.properties.email, person.properties.name,
         person.properties.company, person.properties.role, person.properties.created_at
LIMIT 10
""",
        ),
        # Funnel trends
        _sql_case(
            name="sql_trial_to_paid_conversion_by_cohort_month",
            prompt=(
                "Write a HogQL query that returns the conversion rate from trial signup to paid subscription "
                "by cohort month."
            ),
            expected_sql="""
WITH trial_signups AS (
    SELECT
        person_id,
        date_trunc('month', min(timestamp)) as cohort_month
    FROM events
    WHERE event = 'trial_signup'
    GROUP BY person_id
),
conversions AS (
    SELECT DISTINCT person_id
    FROM events
    WHERE event = 'subscription_started'
)
SELECT
    cohort_month,
    count(DISTINCT t.person_id) as trial_signups,
    count(DISTINCT c.person_id) as paid_conversions,
    (count(DISTINCT c.person_id) * 100.0 / count(DISTINCT t.person_id)) as conversion_rate
FROM trial_signups t
LEFT JOIN conversions c ON t.person_id = c.person_id
GROUP BY cohort_month
ORDER BY cohort_month
""",
        ),
        _sql_case(
            name="sql_median_time_between_pageviews_by_browser",
            prompt=(
                "Write a HogQL query that returns the median time between page views for each browser type, "
                "excluding users with only 1 page view."
            ),
            expected_sql="""
WITH pageview_times AS (
    SELECT
        person_id,
        properties.$browser as browser_type,
        timestamp,
        LAG(timestamp) OVER (PARTITION BY person_id ORDER BY timestamp) as prev_timestamp
    FROM events
    WHERE event = '$pageview'
),
time_diffs AS (
    SELECT
        person_id,
        browser_type,
        dateDiff('second', prev_timestamp, timestamp) as seconds_between_views
    FROM pageview_times
    WHERE prev_timestamp IS NOT NULL
),
user_pageview_counts AS (
    SELECT person_id, count(*) as pageview_count
    FROM events
    WHERE event = '$pageview'
    GROUP BY person_id
    HAVING pageview_count > 1
)
SELECT
    browser_type,
    median(seconds_between_views) as median_seconds_between_views
FROM time_diffs
WHERE person_id IN (SELECT person_id FROM user_pageview_counts)
GROUP BY browser_type
ORDER BY median_seconds_between_views DESC
""",
        ),
        # Correlation — CI version had a tuple-with-extra-context retry; inlined into a single prompt here.
        _sql_case(
            name="sql_feature_churn_correlation_120d",
            prompt=(
                "Write a HogQL query that shows which features are most predictive of churn. "
                "Compute the correlation between feature usage in the first 30 days and churn in the next 60 days. "
                "Use events uploaded_file, downloaded_file, shared_file_link, invited_team_member, "
                "upgraded_plan, downgraded_plan. Use lack of activity as the churn signal. "
                "Analyze the last 120 days of data."
            ),
            expected_sql="""
WITH user_metrics AS (
    SELECT
        fu.person_id,
        fu.uploads_30d,
        fu.downloads_30d,
        fu.shares_30d,
        fu.invites_30d,
        fu.upgrades_30d,
        fu.downgrades_30d,
        fu.total_events_30d,
        cs.churned
    FROM (
        SELECT
            e.person_id,
            countIf(e.event = 'uploaded_file') AS uploads_30d,
            countIf(e.event = 'downloaded_file') AS downloads_30d,
            countIf(e.event = 'shared_file_link') AS shares_30d,
            countIf(e.event = 'invited_team_member') AS invites_30d,
            countIf(e.event = 'upgraded_plan') AS upgrades_30d,
            countIf(e.event = 'downgraded_plan') AS downgrades_30d,
            count() AS total_events_30d,
            MIN(e.timestamp) AS first_activity_date
        FROM events e
        WHERE e.timestamp >= now() - INTERVAL 120 DAY
        GROUP BY e.person_id
        HAVING first_activity_date <= now() - INTERVAL 90 DAY
    ) fu
    INNER JOIN (
        SELECT
            person_id,
            MIN(timestamp) AS first_activity_date,
            CASE
                WHEN MAX(activity_31_90) = 1 THEN 0 ELSE 1
            END AS churned
        FROM (
            SELECT
                person_id,
                timestamp,
                CASE WHEN timestamp >= min_timestamp + INTERVAL 30 DAY AND timestamp < min_timestamp + INTERVAL 90 DAY THEN 1 ELSE 0 END AS activity_31_90,
                min_timestamp
            FROM (
                SELECT
                    person_id,
                    timestamp,
                    MIN(timestamp) OVER (PARTITION BY person_id) AS min_timestamp
                FROM events
                WHERE timestamp >= now() - INTERVAL 120 DAY
            )
        )
        GROUP BY person_id, min_timestamp
        HAVING min_timestamp <= now() - INTERVAL 90 DAY
    ) cs ON fu.person_id = cs.person_id
)

SELECT
    'uploads' AS feature,
    AVG(CASE WHEN churned = 1 THEN uploads_30d ELSE 0 END) AS avg_usage_churned,
    AVG(CASE WHEN churned = 0 THEN uploads_30d ELSE 0 END) AS avg_usage_retained,
    AVG(churned) AS overall_churn_rate,
    AVG(CASE WHEN uploads_30d > 0 THEN churned ELSE NULL END) AS churn_rate_with_feature,
    AVG(CASE WHEN uploads_30d = 0 THEN churned ELSE NULL END) AS churn_rate_without_feature,
    corr(toFloat(uploads_30d), toFloat(churned)) AS correlation_coefficient
FROM user_metrics

UNION ALL

SELECT
    'downloads' AS feature,
    AVG(CASE WHEN churned = 1 THEN downloads_30d ELSE 0 END),
    AVG(CASE WHEN churned = 0 THEN downloads_30d ELSE 0 END),
    AVG(churned),
    AVG(CASE WHEN downloads_30d > 0 THEN churned ELSE NULL END),
    AVG(CASE WHEN downloads_30d = 0 THEN churned ELSE NULL END),
    corr(toFloat(downloads_30d), toFloat(churned))
FROM user_metrics

UNION ALL

SELECT
    'shares' AS feature,
    AVG(CASE WHEN churned = 1 THEN shares_30d ELSE 0 END),
    AVG(CASE WHEN churned = 0 THEN shares_30d ELSE 0 END),
    AVG(churned),
    AVG(CASE WHEN shares_30d > 0 THEN churned ELSE NULL END),
    AVG(CASE WHEN shares_30d = 0 THEN churned ELSE NULL END),
    corr(toFloat(shares_30d), toFloat(churned))
FROM user_metrics

UNION ALL

SELECT
    'invites' AS feature,
    AVG(CASE WHEN churned = 1 THEN invites_30d ELSE 0 END),
    AVG(CASE WHEN churned = 0 THEN invites_30d ELSE 0 END),
    AVG(churned),
    AVG(CASE WHEN invites_30d > 0 THEN churned ELSE NULL END),
    AVG(CASE WHEN invites_30d = 0 THEN churned ELSE NULL END),
    corr(toFloat(invites_30d), toFloat(churned))
FROM user_metrics

UNION ALL

SELECT
    'upgrades' AS feature,
    AVG(CASE WHEN churned = 1 THEN upgrades_30d ELSE 0 END),
    AVG(CASE WHEN churned = 0 THEN upgrades_30d ELSE 0 END),
    AVG(churned),
    AVG(CASE WHEN upgrades_30d > 0 THEN churned ELSE NULL END),
    AVG(CASE WHEN upgrades_30d = 0 THEN churned ELSE NULL END),
    corr(toFloat(upgrades_30d), toFloat(churned))
FROM user_metrics

ORDER BY ABS(corr(toFloat(uploads_30d), toFloat(churned))) DESC
""",
        ),
        _sql_case(
            name="sql_weekly_pageviews_monday_start_4w",
            prompt=(
                "Write a HogQL query that shows weekly pageview counts with Monday as the start of week "
                "for the last 4 weeks."
            ),
            expected_sql="""
SELECT toStartOfWeek(timestamp, 1) as week_start, count(*) as pageview_count
FROM events
WHERE event = '$pageview'
  AND timestamp >= now() - INTERVAL 4 WEEK
GROUP BY week_start
ORDER BY week_start
""",
        ),
        _sql_case(
            name="sql_earliest_session_per_user_30d",
            prompt="Write a HogQL query that returns the earliest session date for each user in the last month.",
            expected_sql="""
SELECT person_id, toDate(min(timestamp)) as first_session_date
FROM events
WHERE timestamp >= now() - INTERVAL 30 DAY
GROUP BY person_id
ORDER BY first_session_date
""",
        ),
        _sql_case(
            name="sql_split_interests_count_users",
            prompt=(
                "Write a HogQL query that splits a comma-separated `interests` property and counts unique users "
                "who have at least one interest set."
            ),
            expected_sql="""
SELECT count(distinct person_id) as users_with_interests
FROM events
WHERE properties.interests IS NOT NULL
  AND length(splitByChar(',', coalesce(properties.interests, ''))) > 0
""",
        ),
    ]

    await SandboxedPublicEval(
        experiment_name=f"sandboxed-sql-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            NoToolCall(forbidden=INSIGHT_WRITE_TOOLS, name="no_persistent_insight_save"),
            RequiredToolCall(required={"execute-sql"}, name="execute_sql_called"),
            LastToolCallNot(
                forbidden={"query-trends", "query-funnel", "query-retention"},
                name="last_call_not_typed_query",
            ),
            SkillLoaded("querying-posthog-data", name="querying_posthog_data_skill_loaded"),
            SQLSchemaAlignment(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
