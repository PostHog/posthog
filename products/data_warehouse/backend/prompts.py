SQL_ASSISTANT_ROOT_SYSTEM_PROMPT = """
<current_hogql_query>
{current_query}
</current_hogql_query>
"""

HOGQL_GENERATOR_USER_PROMPT = """
The current HogQL query (which CAN be empty) is:
<current_query>
{current_query}
</current_query>

Write a new HogQL query or tweak the current one to satisfy this request:
{instructions}

Only return the SQL query, no other text.

STRICTLY FORBIDDEN: templating syntax (double-curly tokens, handlebars, sections).
REQUIRED: All variable references MUST use the "variables." prefix (e.g., variables.org not org).
When the request implies optionality, rewrite it using variables.* with NULL/empty guards exactly as in the examples above.
""".strip()

TIME_PERIOD_PROMPT = """
You must also include a time period in the query if the user asks for one or if the query is related to the events table.
<time_period>
Usually the user will specify a time period in their query. If they don't, use `last 30 days` as a default time period.
If the user asks for a time period, you must include it in the query.
If the user specifies the start date, you should also include the time. The time should be at the start of the day for start date. (e.g. 2025-03-04T00:00:00.000)
If the user specifies the end date, you should also include the time. The time should be at the end of the day for end date. (e.g. 2025-03-05T23:59:59.999)

Examples:
- If the user asks you "find events that happened between March 1st, 2025, and 2025-03-07", you must include `WHERE timestamp >= '2025-03-01T00:00:00.000' AND timestamp <= '2025-03-07T23:59:59.999'` in the query.
- If the user asks you "find events for the last 7 days", you must include `WHERE timestamp >= now() - INTERVAL 7 DAY` in the query.
</time_period>
""".strip()
