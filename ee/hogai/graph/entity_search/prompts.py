FOUND_ENTITIES_MESSAGE_TEMPLATE = """
Successfully found {total_results} entities matching the user's query.

{entities_list}
"""

ENTITY_TYPE_SUMMARY_TEMPLATE = """
**Results by type:**
{entity_type_summary}
"""

HYPERLINK_USAGE_INSTRUCTIONS = """
\n\nVERY IMPORTANT INSTRUCTIONS: ALWAYS WHEN MENTIONING INSIGHTS AND DASHBOARDS IN YOUR RESPONSE, YOU MUST USE THE HYPERLINK FORMAT PROVIDED ABOVE.
For example, write '[Dashboard name](/project/123/dashboard/dashboard_id)' instead of just 'Dashboard name'.
For every insight, write '[Insight name](/project/123/insights/insight_id)' instead of just 'Insight name'.
IF YOU DON'T USE THE HYPERLINK FORMAT, THE USER WILL NOT BE ABLE TO CLICK ON THE INSIGHT OR DASHBOARD NAME AND WILL NOT BE ABLE TO ACCESS THE INSIGHT OR DASHBOARD.
"""
