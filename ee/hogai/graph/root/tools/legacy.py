# The module contains tools that are deprecated and will be replaced in the future with MaxTool implementations.
from pydantic import BaseModel, Field

from ee.hogai.utils.types.base import InsightQuery


# Lower casing matters here. Do not change it.
class create_and_query_insight(BaseModel):
    """
    Use this tool to spawn a subagent that will create a product analytics insight for a given description.
    The tool generates a query and returns formatted text results for a specific data question or iterates on a previous query. It only retrieves a single query per call. If the user asks for multiple insights, you need to decompose a query into multiple subqueries and call the tool for each subquery.

    Follow these guidelines when retrieving data:
    - If the same insight is already in the conversation history, reuse the retrieved data only when this does not violate the <data_analysis_guidelines> section (i.e. only when a presence-check, count, or sort on existing columns is enough).
    - If analysis results have been provided, use them to answer the user's question. The user can already see the analysis results as a chart - you don't need to repeat the table with results nor explain each data point.
    - If the retrieved data and any data earlier in the conversations allow for conclusions, answer the user's question and provide actionable feedback.
    - If there is a potential data issue, retrieve a different new analysis instead of giving a subpar summary. Note: empty data is NOT a potential data issue.
    - If the query cannot be answered with a UI-built insight type - trends, funnels, retention - choose the SQL type to answer the question (e.g. for listing events or aggregating in ways that aren't supported in trends/funnels/retention).

    IMPORTANT: Avoid generic advice. Take into account what you know about the product. Your answer needs to be super high-impact and no more than a few sentences.
    Remember: do NOT retrieve data for the same query more than 3 times in a row.

    # Data schema

    You can pass events, actions, properties, and property values to this tool by specifying the "Data schema" section.

    <example>
    User: Calculate onboarding completion rate for the last week.
    Assistant: I'm going to retrieve the existing data schema first.
    *Retrieves matching events, properties, and property values*
    Assistant: I'm going to create a new trends insight.
    *Calls this tool with the query description: "Trends insight of the onboarding completion rate. Data schema: Relevant matching data schema"*
    </example>

    # Supported insight types
    ## Trends
    A trends insight visualizes events over time using time series. They're useful for finding patterns in historical data.

    The trends insights have the following features:
    - The insight can show multiple trends in one request.
    - Custom formulas can calculate derived metrics, like `A/B*100` to calculate a ratio.
    - Filter and break down data using multiple properties.
    - Compare with the previous period and sample data.
    - Apply various aggregation types, like sum, average, etc., and chart types.
    - And more.

    Examples of use cases include:
    - How the product's most important metrics change over time.
    - Long-term patterns, or cycles in product's usage.
    - The usage of different features side-by-side.
    - How the properties of events vary using aggregation (sum, average, etc).
    - Users can also visualize the same data points in a variety of ways.

    ## Funnel
    A funnel insight visualizes a sequence of events that users go through in a product. They use percentages as the primary aggregation type. Funnels use two or more series, so the conversation history should mention at least two events.

    The funnel insights have the following features:
    - Various visualization types (steps, time-to-convert, historical trends).
    - Filter data and apply exclusion steps.
    - Break down data using a single property.
    - Specify conversion windows, details of conversion calculation, attribution settings.
    - Sample data.
    - And more.

    Examples of use cases include:
    - Conversion rates.
    - Drop off steps.
    - Steps with the highest friction and time to convert.
    - If product changes are improving their funnel over time.
    - Average/median time to convert.
    - Conversion trends over time.

    ## Retention
    A retention insight visualizes how many users return to the product after performing some action. They're useful for understanding user engagement and retention.

    The retention insights have the following features: filter data, sample data, and more.

    Examples of use cases include:
    - How many users come back and perform an action after their first visit.
    - How many users come back to perform action X after performing action Y.
    - How often users return to use a specific feature.

    ## SQL
    The 'sql' insight type allows you to write arbitrary SQL queries to retrieve data.

    The SQL insights have the following features:
    - Filter data using arbitrary SQL.
    - All ClickHouse SQL features.
    - You can nest subqueries as needed.
    """

    query_description: str = Field(
        description=(
            "A description of the query to generate, encapsulating the details of the user's request. "
            "Include all relevant context from earlier messages too, as the tool won't see that conversation history. "
            "If an existing insight has been used as a starting point, include that insight's filters and query in the description. "
            "Don't be overly prescriptive with event or property names, unless the user indicated they mean this specific name (e.g. with quotes). "
            "If the users seems to ask for a list of entities, rather than a count, state this explicitly."
        )
    )


class session_summarization(BaseModel):
    """
    Use this tool to summarize session recordings by analysing the events within those sessions to find patterns and issues.
    It will return a textual summary of the captured session recordings.

    # When to use the tool:
    When the user asks to summarize session recordings:
    - "summarize" synonyms: "watch", "analyze", "review", and similar
    - "session recordings" synonyms: "sessions", "recordings", "replays", "user sessions", and similar

    # When NOT to use the tool:
    - When the user asks to find, search for, or look up session recordings, but doesn't ask to summarize them
    - When users asks to update, change, or adjust session recordings filters

    # Synonyms
    - "summarize": "watch", "analyze", "review", and similar
    - "session recordings": "sessions", "recordings", "replays", "user sessions", and similar

    # Managing context
    If the conversation history contains context about the current filters or session recordings, follow these steps:
    - Convert the user query into a `session_summarization_query`
    - The query should be used to understand the user's intent
    - Decide if the query is relevant to the current filters and set `should_use_current_filters` accordingly
    - Generate the `summary_title` based on the user's query and the current filters
    - Extract the `session_summarization_limit` from the user's query, if present

    Otherwise:
    - Convert the user query into a `session_summarization_query`
    - The query should be used to search for relevant sessions and then summarize them
    - Assume the `should_use_current_filters` should be always `false`
    - Generate the `summary_title` based on the user's query
    - Extract the `session_summarization_limit` from the user's query if present

    # Additional guidelines
    - CRITICAL: Always pass the user's complete, unmodified query to the `session_summarization_query` parameter
    - DO NOT truncate, summarize, or extract keywords from the user's query
    - The query is used to find relevant sessions - context helps find better matches
    - Use explicit tool definition to make a decision
    """

    session_summarization_query: str = Field(
        description="""
        - The user's complete query for session recordings summarization.
        - This will be used to find relevant session recordings.
        - Always pass the user's complete, unmodified query.
        - Examples:
          * 'summarize all session recordings from yesterday'
          * 'analyze mobile user session recordings from last week, even if 1 second'
          * 'watch last 300 session recordings of MacOS users from US'
          * and similar
        """
    )
    should_use_current_filters: bool = Field(
        description="""
        - Whether to use current filters from user's UI to find relevant session recordings.
        - IMPORTANT: Should be always `false` if the current filters or `search_session_recordings` tool are not present in the conversation history.
        - Examples:
          * Set to `true` if one of the conditions is met:
            - the user wants to summarize "current/selected/opened/my/all/these" session recordings
            - the user wants to use "current/these" filters
            - the user's query specifies filters identical to the current filters
            - if the user's query doesn't specify any filters/conditions
            - the user refers to what they're "looking at" or "viewing"
          * Set to `false` if one of the conditions is met:
            - no current filters or `search_session_recordings` tool are present in the conversation
            - the user specifies date/time period different from the current filters
            - the user specifies conditions (user, device, id, URL, etc.) not present in the current filters
        """,
    )
    summary_title: str = Field(
        description="""
        - The name of the summary that is expected to be generated from the user's `session_summarization_query` and/or `current_filters` (if present).
        - The name should cover in 3-7 words what sessions would be to be summarized in the summary
        - This won't be used for any search of filtering, only to properly label the generated summary.
        - Examples:
          * If `should_use_current_filters` is `false`, then the `summary_title` should be generated based on the `session_summarization_query`:
            - query: "I want to watch all the sessions of user `user@example.com` in the last 30 days no matter how long" -> name: "Sessions of the user user@example.com (last 30 days)"
            - query: "summarize my last 100 session recordings" -> name: "Last 100 sessions"
            - and similar
          * If `should_use_current_filters` is `true`, then the `summary_title` should be generated based on the current filters in the context (if present):
            - filters: "{"key":"$os","value":["Mac OS X"],"operator":"exact","type":"event"}" -> name: "MacOS users"
            - filters: "{"date_from": "-7d", "filter_test_accounts": True}" -> name: "All sessions (last 7 days)"
            - and similar
          * If there's not enough context to generated the summary name - keep it an empty string ("")
        """
    )
    session_summarization_limit: int = Field(
        description="""
        - The maximum number of sessions to summarize
        - This will be used to apply to DB query to limit the results.
        - Extract the limit from the user's query if present. Set to -1 if not present.
        - IMPORTANT: Extract the limit only if the user's query explicitly mentions a number of sessions to summarize.
        - Examples:
          * 'summarize all sessions from yesterday' -> limit: -1
          * 'summarize last 100 sessions' -> limit: 100
          * 'summarize these sessions' -> limit: -1
          * 'summarize first 10 of these sessions' -> limit: 10
          * 'summarize the sessions of the users with at least 10 events' -> limit: -1
          * 'summarize the sessions of the last 30 days' -> limit: -1
          * 'summarize last 500 sessions of the MacOS users from US' -> limit: 500
          * and similar
        """
    )


class create_dashboard(BaseModel):
    """
    Use this tool when users ask to create, build, or make a new dashboard with insights.
    This tool will search for existing insights that match the user's requirements so no need to call `search_insights` tool, or create new insights if none are found, then combine them into a dashboard.
    Do not call this tool if the user only asks to find, search for, or look up existing insights and does not ask to create a dashboard.
    If you decided to use this tool, there is no need to call `search_insights` tool beforehand. The tool will search for existing insights that match the user's requirements and create new insights if none are found.
    """

    search_insights_queries: list[InsightQuery] = Field(
        description="A list of insights to be included in the dashboard. Include all the insights that the user mentioned."
    )
    dashboard_name: str = Field(
        description=(
            "The name of the dashboard to be created based on the user request. It should be short and concise as it will be displayed as a header in the dashboard tile."
        )
    )
