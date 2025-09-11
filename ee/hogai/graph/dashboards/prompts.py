DASHBOARD_NAME_GENERATION_SYSTEM_PROMPT = """
You are an AI assistant tasked with generating concise, descriptive dashboard names based on user queries and the insights that will be included.

Given the user's request and the list of insights to be included in the dashboard, create a clear, professional dashboard name that:
1. Reflects the main theme or purpose of the dashboard
2. Is concise (2-6 words typically)
3. Uses title case formatting
4. Avoids generic terms like "Dashboard" or "Analytics" in the name
5. If an insight was not able to be created do not use the insight name in the dashboard name.

Examples:
- User wants to track user engagement → "User Engagement Overview"
- User wants to see signup funnel and retention → "User Acquisition & Retention"
- User asks for product usage metrics → "Product Usage Metrics"
- User wants revenue and conversion data → "Revenue & Conversions"

User Query: {user_query}
Insight descriptions:
\n\n

{insights_summary}

Generate only the dashboard name, nothing else.
"""

DASHBOARD_CREATION_ERROR_MESSAGE = """
I encountered an issue while creating the dashboard. Please try again.
"""

DASHBOARD_SUCCESS_MESSAGE_TEMPLATE = """
**Dashboard Created**

The dashboard [{dashboard_name}]({dashboard_url}) was created.
The dashboard contains {insight_count} insight{insight_plural}.

**Included insights**
{insights_list}

"""
QUERIES_WITHOUT_INSIGHTS_MESSAGE_TEMPLATE = """
**Queries without insights**
Due to issues with creating insights, the following queries were not included in the dashboard:
{queries_without_insights}
"""
HYPERLINK_USAGE_INSTRUCTIONS = """
\n\nVERY IMPORTANT INSTRUCTIONS: ALWAYS WHEN MENTIONING INSIGHTS AND DASHBOARDS IN YOUR RESPONSE, YOU MUST USE THE HYPERLINK FORMAT PROVIDED ABOVE.
For example, write '[Dashboard name](/project/123/dashboard/dashboard_id)' instead of just 'Dashboard name'.
For every insight, write '[Insight name](/project/123/insights/insight_id)' instead of just 'Insight name'.
IF YOU DON'T USE THE HYPERLINK FORMAT, THE USER WILL NOT BE ABLE TO CLICK ON THE INSIGHT OR DASHBOARD NAME AND WILL NOT BE ABLE TO ACCESS THE INSIGHT OR DASHBOARD.
"""


DASHBOARD_NO_INSIGHTS_MESSAGE = """
No existing insights matched the user's request and new insights were not able to be created.

From the insight creation process, the message was:

{subgraph_last_message}

"""
