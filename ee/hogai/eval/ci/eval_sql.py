import pytest

from asgiref.sync import sync_to_async
from braintrust import EvalCase, Score
from braintrust_core.score import Scorer
from langchain_core.runnables import RunnableConfig

from posthog.schema import AgentMode, AssistantMessage, HumanMessage

from posthog.models import Team

from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.eval.scorers.sql import SQLSemanticsCorrectness, evaluate_sql_query
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from ee.models.assistant import Conversation

from ..base import MaxPublicEval


def _has_execute_sql_call(state: AssistantState) -> bool:
    for msg in state.messages:
        if isinstance(msg, AssistantMessage) and msg.tool_calls:
            for tool_call in msg.tool_calls:
                if tool_call.name == "execute_sql":
                    return True
    return False


def _extract_sql_result(state: AssistantState) -> dict:
    result: dict = {"tool_called": False, "query": None}
    for msg in state.messages:
        if isinstance(msg, AssistantMessage) and msg.tool_calls:
            for tool_call in msg.tool_calls:
                if tool_call.name == "execute_sql":
                    result["tool_called"] = True
                    result["query"] = tool_call.args.get("query")
    return result


class ExecuteSQLToolCalled(Scorer):
    """Binary scorer: did the agent call execute_sql?"""

    def _name(self):
        return "execute_sql_tool_called"

    async def _run_eval_async(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        return self._evaluate(output)

    def _evaluate(self, output) -> Score:
        called = output.get("tool_called", False) if output else False
        return Score(name=self._name(), score=1.0 if called else 0.0)


class HogQLQuerySyntaxCorrectness(Scorer):
    def _name(self):
        return "sql_syntax_correctness"

    async def _run_eval_async(self, output, *args, **kwargs):
        return await sync_to_async(self._evaluate)(output)

    def _run_eval_sync(self, output, *args, **kwargs):
        return self._evaluate(output)

    def _evaluate(self, output) -> Score:
        team = Team.objects.latest("created_at")
        query = output.get("query") if output else None
        return evaluate_sql_query(self._name(), query, team)


class CISQLSemanticsCorrectness(SQLSemanticsCorrectness):
    """Wraps the shared scorer to extract `query` from the CI eval output dict."""

    async def _run_eval_async(self, output, expected=None, database_schema=None, **kwargs):
        query = output.get("query") if output else None
        return await super()._run_eval_async(query, expected, database_schema=database_schema, **kwargs)

    def _run_eval_sync(self, output, expected=None, database_schema=None, **kwargs):
        query = output.get("query") if output else None
        return super()._run_eval_sync(query, expected, database_schema=database_schema, **kwargs)


@pytest.fixture
def call_agent_for_sql(demo_org_team_user):
    _, team, user = demo_org_team_user
    graph = (
        AssistantGraph(team, user)
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root()
        .compile(checkpointer=DjangoCheckpointer())
    )

    async def callable(query_with_extra_context: str | tuple[str, str]) -> dict:
        query = query_with_extra_context[0] if isinstance(query_with_extra_context, tuple) else query_with_extra_context
        conversation = await Conversation.objects.acreate(team=team, user=user)
        initial_state = AssistantState(
            messages=[HumanMessage(content=query)],
            agent_mode=AgentMode.SQL,
        )
        config = RunnableConfig(configurable={"thread_id": conversation.id})
        raw_state = await graph.ainvoke(initial_state, config)
        state = AssistantState.model_validate(raw_state)

        if isinstance(query_with_extra_context, tuple) and not _has_execute_sql_call(state):
            state.messages = [*state.messages, HumanMessage(content=query_with_extra_context[1])]
            state.graph_status = "resumed"
            raw_state = await graph.ainvoke(state, config)
            state = AssistantState.model_validate(raw_state)

        return _extract_sql_result(state)

    yield callable


@pytest.mark.django_db
async def eval_sql(call_agent_for_sql, pytestconfig):
    all_cases: list[EvalCase] = [
        ### Straightforward breakdowns
        EvalCase(
            input="Count pageviews by browser",
            expected="""
SELECT properties.$browser as browser, count(*) as pageview_count
FROM events
WHERE event = '$pageview'
GROUP BY browser
ORDER BY pageview_count DESC
LIMIT 100
""",
        ),
        EvalCase(
            input="What are the top 10 countries by number of users in the last 7 days?",
            expected="""
SELECT properties.$geoip_country_name as country, count(distinct person_id) as user_count
FROM events
WHERE timestamp >= now() - interval 7 day
GROUP BY country
ORDER BY user_count DESC
LIMIT 10
""",
        ),
        ### Session duration
        EvalCase(
            input="Show me the average session duration by day of week",
            expected="""
SELECT toDayOfWeek(timestamp) as day_of_week,
       avg(session.$session_duration) as avg_session_duration
FROM events
GROUP BY day_of_week
ORDER BY day_of_week
""",
        ),
        EvalCase(
            input="What percentage of users who visited the pricing page made a purchase in this month?",
            expected="""
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
        ### Conversion
        EvalCase(
            input="How many users completed the onboarding flow (viewed welcome page, created profile, and completed tutorial) in sequence?",
            expected="""
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
        EvalCase(
            input="How many users completed the onboarding flow (viewed welcome page, created profile, and completed tutorial) regardless of sequence?",
            expected="""
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
        ### Property math
        EvalCase(
            input="The number of distinct values of property $browser seen in each of the last 14 days",
            expected="""
SELECT date_trunc('day', timestamp) as day, count(distinct properties.$browser) as distinct_browser_count
FROM events
WHERE event = '$pageview'
  AND timestamp >= now() - INTERVAL 14 DAY
GROUP BY day
ORDER BY day
""",
        ),
        EvalCase(
            input="Sum up the total amounts paid for the 'paid_bill' event over the past month for Hedgebox Inc.",
            expected="""
SELECT sum(toFloat(properties.amount_usd)) AS total_amount_paid
FROM events
WHERE event = 'paid_bill'
  AND timestamp >= now() - INTERVAL 30 DAY
  AND organization.properties.name = 'Hedgebox Inc.'
""",
        ),
        ### Open questions to list persons
        EvalCase(
            input="Who are the 5 users I should interview around file download usage?",
            expected="""
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
        EvalCase(
            input="Who are the 5 users that have downloaded the most files in the past few weeks? Who are they?",
            expected="""
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
        EvalCase(
            input="Show me 10 example person profiles of file download users",
            expected="""
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
        ### Funnel trends
        EvalCase(
            input="What's the conversion rate from trial signup to paid subscription by cohort month?",
            expected="""
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
        EvalCase(
            input="Show me the median time between page views for each browser type, excluding users with only 1 page view",
            expected="""
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
        ### Correlation
        EvalCase(
            input=(
                "Which features are most predictive of churn? Show correlation between feature usage in first 30 days and churn in next 60 days",
                "Use events uploaded_file, downloaded_file, shared_file_link, invited_team_member, upgraded_plan, downgraded_plan. Use lack of activity as the churn signal. Analyze the last 120 days of data.",
            ),
            expected="""
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
        EvalCase(
            input="Show weekly pageview counts with Monday as the start of week for the last 4 weeks",
            expected="""
SELECT toStartOfWeek(timestamp, 1) as week_start, count(*) as pageview_count
FROM events
WHERE event = '$pageview'
  AND timestamp >= now() - INTERVAL 4 WEEK
GROUP BY week_start
ORDER BY week_start
""",
        ),
        EvalCase(
            input="Get the earliest session date for each user in the last month",
            expected="""
SELECT person_id, toDate(min(timestamp)) as first_session_date
FROM events
WHERE timestamp >= now() - INTERVAL 30 DAY
GROUP BY person_id
ORDER BY first_session_date
""",
        ),
        EvalCase(
            input="I want to split a comma-separated interests property and count unique users",
            expected="""
SELECT count(distinct person_id) as users_with_interests
FROM events
WHERE properties.interests IS NOT NULL
  AND length(splitByChar(',', coalesce(properties.interests, ''))) > 0
""",
        ),
    ]

    await MaxPublicEval(
        experiment_name="sql",
        task=call_agent_for_sql,
        scores=[
            ExecuteSQLToolCalled(),
            HogQLQuerySyntaxCorrectness(),
            CISQLSemanticsCorrectness(),
        ],
        data=all_cases,
        pytestconfig=pytestconfig,
    )
