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
