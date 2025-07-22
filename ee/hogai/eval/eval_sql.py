import pytest
from asgiref.sync import sync_to_async
from braintrust import EvalCase, Score
from braintrust_core.score import Scorer

from ee.hogai.graph.sql.toolkit import SQL_SCHEMA
from posthog.errors import InternalCHQueryError
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.models.team.team import Team
from posthog.schema import AssistantHogQLQuery, NodeKind

from .conftest import MaxEval
from .scorers import PlanAndQueryOutput, PlanCorrectness, QueryAndPlanAlignment, QueryKindSelection, TimeRangeRelevancy

QUERY_GENERATION_MAX_RETRIES = 3


class RetryEfficiency(Scorer):
    """Evaluate the efficiency of SQL query generation based on retry attempts. Higher scores for fewer retries."""

    def _name(self):
        return "retry_efficiency"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        retry_count = output.get("query_generation_retry_count", 0) if output else 0

        # Score is inversely proportional to retry count
        score = 1.0 if retry_count == 0 else 1 - (retry_count / QUERY_GENERATION_MAX_RETRIES)

        return Score(name=self._name(), score=score, metadata={"query_generation_retry_count": retry_count})

    def _run_eval_sync(self, output, expected=None, **kwargs):
        retry_count = output.get("query_generation_retry_count", 0) if output else 0

        # Score is inversely proportional to retry count
        score = 1.0 if retry_count == 0 else 1 - (retry_count / QUERY_GENERATION_MAX_RETRIES)

        return Score(name=self._name(), score=score, metadata={"query_generation_retry_count": retry_count})


class SQLSyntaxCorrectness(Scorer):
    """Evaluate if the generated SQL query has correct syntax."""

    def _name(self):
        return "sql_syntax_correctness"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        if not output:
            return Score(
                name=self._name(), score=None, metadata={"reason": "No SQL query to verify, skipping evaluation"}
            )
        query = {"query": output}
        team = await Team.objects.alatest("created_at")
        try:
            # Try to parse, print, and run the query
            await sync_to_async(HogQLQueryRunner(query, team).calculate)()
        except BaseHogQLError as e:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"HogQL-level error: {str(e)}"})
        except InternalCHQueryError as e:
            return Score(name=self._name(), score=0.5, metadata={"reason": f"ClickHouse-level error: {str(e)}"})
        else:
            return Score(name=self._name(), score=1.0)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        if not output:
            return Score(
                name=self._name(), score=None, metadata={"reason": "No SQL query to verify, skipping evaluation"}
            )
        query = {"query": output}
        team = Team.objects.latest("created_at")
        try:
            # Try to parse, print, and run the query
            HogQLQueryRunner(query, team).calculate()
        except BaseHogQLError as e:
            return Score(name=self._name(), score=0.0, metadata={"reason": f"HogQL-level error: {str(e)}"})
        except InternalCHQueryError as e:
            return Score(name=self._name(), score=0.5, metadata={"reason": f"ClickHouse-level error: {str(e)}"})
        else:
            return Score(name=self._name(), score=1.0)


class HogQLQuerySyntaxCorrectness(SQLSyntaxCorrectness):
    async def _run_eval_async(self, output, expected=None, **kwargs):
        return await super()._run_eval_async(
            output["query"].query if output and output.get("query") else None, expected, **kwargs
        )

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return super()._run_eval_sync(
            output["query"].query if output and output.get("query") else None, expected, **kwargs
        )


@pytest.mark.django_db
async def eval_sql(call_root_for_insight_generation):
    all_cases: list[EvalCase] = [
        EvalCase(
            input="Count pageviews by browser, using SQL",
            expected=PlanAndQueryOutput(
                plan="""
Query to count pageviews grouped by browser:
- FROM: events table
- WHERE: event = '$pageview'
- GROUP BY: properties.$browser
- SELECT: properties.$browser, count(*) as pageview_count
- ORDER BY: pageview_count DESC
""",
                query=AssistantHogQLQuery(
                    query="""
SELECT properties.$browser as browser, count(*) as pageview_count
FROM events
WHERE event = '$pageview'
GROUP BY browser
ORDER BY pageview_count DESC
LIMIT 100
"""
                ),
            ),
        ),
        EvalCase(
            input="What are the top 10 countries by number of users in the last 7 days? Use SQL",
            expected=PlanAndQueryOutput(
                plan="""
Query to find the top 10 countries by number of users in the last 7 days:
- FROM: events table
- WHERE: timestamp >= now() - interval 7 day
- GROUP BY: properties.$geoip_country_name
- SELECT: properties.$geoip_country_name, count(distinct person_id) as user_count
- ORDER BY: user_count DESC
- LIMIT: 10
""",
                query=AssistantHogQLQuery(
                    query="""
SELECT properties.$geoip_country_name as country, count(distinct person_id) as user_count
FROM events
WHERE timestamp >= now() - interval 7 day
GROUP BY country
ORDER BY user_count DESC
LIMIT 10
"""
                ),
            ),
        ),
        EvalCase(
            input="Show me the average session duration by day of week, using SQL",
            expected=PlanAndQueryOutput(
                plan="""
Query to calculate average session duration by day of week:
- FROM: sessions table (or equivalent calculation)
- SELECT: day_of_week(timestamp), avg(session_duration)
- GROUP BY: day_of_week
- ORDER BY: day_of_week
""",
                query=AssistantHogQLQuery(
                    query="""
SELECT toDayOfWeek(timestamp) as day_of_week,
       avg(session.$session_duration) as avg_session_duration
FROM events
GROUP BY day_of_week
ORDER BY day_of_week
"""
                ),
            ),
        ),
        EvalCase(
            input="What percentage of users who visited the pricing page made a purchase in this month? Use SQL",
            expected=PlanAndQueryOutput(
                plan="""
Query to calculate the percentage of users who visited the pricing page and also made a purchase this month:
- Subquery 1: Find distinct users who visited pricing page this month
- Subquery 2: Find distinct users who made a purchase this month
- Calculate: (Users who did both) / (Users who visited pricing page) * 100
- Time filter: date_trunc('month', timestamp) = date_trunc('month', now())
""",
                query=AssistantHogQLQuery(
                    query="""
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
"""
                ),
            ),
        ),
        EvalCase(
            input="How many users completed the onboarding flow (viewed welcome page, created profile, and completed tutorial) in sequence? Use SQL",
            expected=PlanAndQueryOutput(
                plan="""
Query to count users who completed the full onboarding sequence:
- Use window functions to assign sequence numbers to each step
- Check that users have all three steps in the correct order
- Count distinct users who completed all steps
""",
                query=AssistantHogQLQuery(
                    query="""
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
"""
                ),
            ),
        ),
        EvalCase(
            input="How many users completed the onboarding flow (viewed welcome page, created profile, and completed tutorial) regardless of sequence? Use SQL",
            expected=PlanAndQueryOutput(
                plan="""
Query to count users who completed the full onboarding sequence:
- Aggregate occurences of each event per user
- Count users who have all three events
""",
                query=AssistantHogQLQuery(
                    query="""
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
"""
                ),
            ),
        ),
        EvalCase(
            # As of May 2025, trends insights don't support "number of distinct values of property" math, so we MUST use SQL here
            input="The number of distinct values of property $browser seen in each of the last 14 days",
            expected=PlanAndQueryOutput(
                plan="""
Query:
- Count distinct values of property $browser seen in each of the last 14 days
""",
                query=AssistantHogQLQuery(
                    query="""
SELECT date_trunc('day', timestamp) as day, count(distinct properties.$browser) as distinct_browser_count
FROM events
WHERE event = '$pageview'
  AND timestamp >= now() - INTERVAL 14 DAY
GROUP BY day
ORDER BY day
"""
                ),
            ),
        ),
        EvalCase(
            input="Sum up the total amounts paid for the 'paid_bill' event over the past month for Hedgebox Inc. Make sure to use SQL.",
            expected=PlanAndQueryOutput(
                plan="Logic:\n- Filter the 'paid_bill' events for the past month.\n- Sum the 'amount_usd' property for these events.\n- Ensure the events are associated with 'Hedgebox Inc.' by filtering using the 'name' property of the 'organization' entity.\n\nSources:\n- Event: 'paid_bill'\n  - Use the 'amount_usd' property to calculate the total amount paid.\n  - Filter events to the past month.\n- Entity: 'organization'\n  - Use the 'name' property to filter for 'Hedgebox Inc.'",
                query=AssistantHogQLQuery(
                    query="""
SELECT sum(toFloat(properties.amount_usd)) AS total_amount_paid
FROM events
WHERE event = 'paid_bill'
  AND timestamp >= now() - INTERVAL 30 DAY
  AND organization.properties.name = 'Hedgebox Inc.'
"""
                ),
            ),
        ),
        EvalCase(
            input="Who are the 5 users I should interview around file download usage?",
            expected=PlanAndQueryOutput(
                plan="""
Query to find the 5 users to interview around file download usage:
- FROM: events table
- WHERE: event contains file download usage patterns or properties related to file download
- GROUP BY: person_id to get unique users
- SELECT: person.properties (name, email, etc.) and usage metrics
- ORDER BY: usage frequency or recency
- LIMIT: 5
""",
                query=AssistantHogQLQuery(
                    query="""
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
"""
                ),
            ),
        ),
        EvalCase(
            input="Who are the 5 users that have downloaded the most files in the past few weeks? Who are they?",
            expected=PlanAndQueryOutput(
                plan="""
Query to find the 5 users who downloaded the most files in the past few weeks:
- FROM: events table
- WHERE: event = 'downloaded_file', timestamp in past few weeks
- GROUP BY: person_id
- SELECT: person details and count of downloads
- ORDER BY: download count DESC
- LIMIT: 5
""",
                query=AssistantHogQLQuery(
                    query="""
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
"""
                ),
            ),
        ),
        EvalCase(
            input="Show me 10 example person profiles of file download users",
            expected=PlanAndQueryOutput(
                plan="""
Query to show 10 example person profiles of file download users:
- FROM: events table joined with person data
- WHERE: events related to file download usage
- GROUP BY: person_id to get unique users
- SELECT: person profile information (properties)
- LIMIT: 10
""",
                query=AssistantHogQLQuery(
                    query="""
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
"""
                ),
            ),
        ),
        # Cases that should be solved after this PR (with improved documentation)
        EvalCase(
            input="What's the conversion rate from trial signup to paid subscription by cohort month?",
            expected=PlanAndQueryOutput(
                plan="""
Query to calculate conversion rate from trial signup to paid subscription by cohort month:
- Define cohort month as the month when users first signed up for trial
- For each cohort month, count trial signups and paid conversions
- Calculate conversion rate as (paid conversions / trial signups) * 100
- Use window functions and conditional aggregation
""",
                query=AssistantHogQLQuery(
                    query="""
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
"""
                ),
            ),
        ),
        EvalCase(
            input="Show me the median time between page views for each browser type, excluding users with only 1 page view",
            expected=PlanAndQueryOutput(
                plan="""
Query to calculate median time between page views by browser type:
- Filter to pageview events only
- Use window functions to calculate time differences between consecutive pageviews per user
- Group by browser type (from event properties)
- Calculate median using quantile functions
- Exclude users with only 1 pageview
""",
                query=AssistantHogQLQuery(
                    query="""
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
    td.browser_type,
    quantile(0.5)(td.seconds_between_views) as median_seconds_between_views
FROM time_diffs td
INNER JOIN user_pageview_counts upc ON td.person_id = upc.person_id
WHERE td.browser_type IS NOT NULL
GROUP BY td.browser_type
ORDER BY median_seconds_between_views
"""
                ),
            ),
        ),
        EvalCase(
            input="Which features are most predictive of churn? Show correlation between feature usage in first 30 days and churn in next 60 days",
            expected=PlanAndQueryOutput(
                plan="""
Query to analyze feature usage correlation with churn:
- Define user cohorts based on signup date
- Track feature usage in first 30 days after signup
- Identify churn status in days 31-90 after signup
- Calculate correlation between each feature usage and churn
- Use statistical functions to measure predictive power
""",
                query=AssistantHogQLQuery(
                    query="""
WITH user_signups AS (
    SELECT
        person_id,
        min(timestamp) as signup_date
    FROM events
    WHERE event = 'user_signup'
    GROUP BY person_id
),
feature_usage AS (
    SELECT
        us.person_id,
        us.signup_date,
        properties.feature_name as feature,
        count(*) as usage_count
    FROM events e
    INNER JOIN user_signups us ON e.person_id = us.person_id
    WHERE event = 'feature_used'
      AND e.timestamp BETWEEN us.signup_date AND us.signup_date + INTERVAL 30 DAY
    GROUP BY us.person_id, us.signup_date, properties.feature_name
),
churn_status AS (
    SELECT
        us.person_id,
        us.signup_date,
        CASE WHEN max(e.timestamp) < us.signup_date + INTERVAL 90 DAY THEN 1 ELSE 0 END as is_churned
    FROM user_signups us
    LEFT JOIN events e ON us.person_id = e.person_id AND e.timestamp > us.signup_date + INTERVAL 30 DAY
    GROUP BY us.person_id, us.signup_date
)
SELECT
    fu.feature,
    avg(fu.usage_count) as avg_usage,
    avg(CASE WHEN cs.is_churned = 1 THEN fu.usage_count ELSE 0 END) as avg_usage_churned,
    avg(CASE WHEN cs.is_churned = 0 THEN fu.usage_count ELSE 0 END) as avg_usage_retained,
    corr(fu.usage_count, cs.is_churned) as churn_correlation
FROM feature_usage fu
INNER JOIN churn_status cs ON fu.person_id = cs.person_id
GROUP BY fu.feature
ORDER BY abs(churn_correlation) DESC
"""
                ),
            ),
        ),
        # Cases that may still fail (very challenging)
        EvalCase(
            input="Create a customer health score combining recency, frequency, and monetary value with weighted percentiles",
            expected=PlanAndQueryOutput(
                plan="""
Query to create RFM-based customer health score:
- Calculate Recency: days since last purchase
- Calculate Frequency: number of purchases in period
- Calculate Monetary: total purchase value
- Convert each to percentile ranks
- Apply weights and combine into health score
- Use advanced window functions and statistical calculations
""",
                query=AssistantHogQLQuery(
                    query="""
WITH customer_rfm AS (
    SELECT
        person_id,
        max(timestamp) as last_purchase,
        count(*) as purchase_frequency,
        sum(toFloat(properties.amount_usd)) as total_monetary_value,
        dateDiff('day', max(timestamp), now()) as recency_days
    FROM events
    WHERE event = 'purchase'
      AND timestamp >= now() - INTERVAL 365 DAY
    GROUP BY person_id
),
rfm_percentiles AS (
    SELECT
        person_id,
        recency_days,
        purchase_frequency,
        total_monetary_value,
        percent_rank() OVER (ORDER BY recency_days ASC) as recency_percentile,
        percent_rank() OVER (ORDER BY purchase_frequency DESC) as frequency_percentile,
        percent_rank() OVER (ORDER BY total_monetary_value DESC) as monetary_percentile
    FROM customer_rfm
)
SELECT
    person_id,
    recency_days,
    purchase_frequency,
    total_monetary_value,
    (recency_percentile * 0.3 + frequency_percentile * 0.4 + monetary_percentile * 0.3) as health_score,
    CASE
        WHEN (recency_percentile * 0.3 + frequency_percentile * 0.4 + monetary_percentile * 0.3) >= 0.8 THEN 'Champion'
        WHEN (recency_percentile * 0.3 + frequency_percentile * 0.4 + monetary_percentile * 0.3) >= 0.6 THEN 'Loyal'
        WHEN (recency_percentile * 0.3 + frequency_percentile * 0.4 + monetary_percentile * 0.3) >= 0.4 THEN 'Potential'
        WHEN (recency_percentile * 0.3 + frequency_percentile * 0.4 + monetary_percentile * 0.3) >= 0.2 THEN 'At Risk'
        ELSE 'Lost'
    END as customer_segment
FROM rfm_percentiles
ORDER BY health_score DESC
"""
                ),
            ),
        ),
    ]

    await MaxEval(
        experiment_name="sql",
        task=call_root_for_insight_generation,
        scores=[
            QueryKindSelection(expected=NodeKind.HOG_QL_QUERY),
            PlanCorrectness(
                query_kind=NodeKind.HOG_QL_QUERY,
                evaluation_criteria="""
1. A plan must define a clear intent for the SQL query to be generated, including which tables/entities are being queried, what filters are being applied, and what is being returned.
2. Compare tables, entities, filters, aggregations, group by clauses, and any other SQL elements mentioned in the 'expected plan' and 'output plan'.
3. Check if the outlined query in 'output plan' can answer the user's question according to the 'expected plan'.
4. If 'expected plan' mentions specific joins, aggregations, or window functions, check if 'output plan' includes similar operations, and heavily penalize if they are not present or significantly different.
5. If 'expected plan' mentions specific time range filters, check if 'output plan' includes similar time range filters, and heavily penalize if they are not present or different.
6. Heavily penalize if the 'output plan' contains any excessive operations not present in the 'expected plan' that would change the meaning of the query.
""",
            ),
            QueryAndPlanAlignment(
                query_kind=NodeKind.HOG_QL_QUERY,
                json_schema=SQL_SCHEMA,
                evaluation_criteria="""
Most importantly, evaluate the `query` field, containing the generated HogQL.
HogQL is simply an SQL flavor derived from ClickHouse SQL, with some PostHog-specific syntax.
The most important piece of PostHog-specific syntax is easy access to JSON properties, which is done using `.`, like so: `SELECT properties.$browser FROM events`.
It's also possible to access nested tables, such the `events` table has a `person` field that actually points to the related row in the `persons` table (the concrete field on `events` is `person_id`).
This means the following syntax is valid and useful too: `SELECT person.properties.foo.bar FROM events`.
The other standard table is `sessions`, which contains data of the session the event belongs to (though events can be outside of a session as well).

Important points:
- The generated query should use `person_id` or `person.id` for any aggregation on unique users, should NOT be using `distinct_id` or properties.
- $identify generally should not be used, as they're mostly for internal purposes, and not useful for insights. A more useful event (or no event filter) should be used.
- For session duration, `session.$session_duration` should be used instead of things like `properties.$session_duration`.""",
            ),
            HogQLQuerySyntaxCorrectness(),
            TimeRangeRelevancy(query_kind=NodeKind.HOG_QL_QUERY),
            RetryEfficiency(),
        ],
        data=all_cases,
    )
