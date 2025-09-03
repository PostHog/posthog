DASHBOARD_NAME_GENERATION_SYSTEM_PROMPT = """
You are an AI assistant tasked with generating concise, descriptive dashboard names based on user queries and the insights that will be included.

Given the user's request and the list of insights to be included in the dashboard, create a clear, professional dashboard name that:
1. Reflects the main theme or purpose of the dashboard
2. Is concise (2-6 words typically)
3. Uses title case formatting
4. Avoids generic terms like "Dashboard" or "Analytics" in the name

Examples:
- User wants to track user engagement → "User Engagement Overview"
- User wants to see signup funnel and retention → "User Acquisition & Retention"
- User asks for product usage metrics → "Product Usage Metrics"
- User wants revenue and conversion data → "Revenue & Conversions"

User Query: {user_query}
Insights to include: {insights_summary}

Generate only the dashboard name, nothing else.
"""

DASHBOARD_CREATION_ERROR_MESSAGE = """
I encountered an issue while creating your dashboard. This could be due to:
- Problems accessing the insights
- Database connectivity issues
- Insufficient permissions

Please try again with a more specific request, or contact support if the issue persists.
"""

DASHBOARD_SUCCESS_MESSAGE_TEMPLATE = """
✅ **Dashboard Created Successfully!**

I've created your dashboard "{dashboard_name}" with {insight_count} insight{insight_plural}.

**Included insights:**
{insights_list}

You can view your dashboard [here](/dashboard/{dashboard_id}).
"""

DASHBOARD_NO_INSIGHTS_MESSAGE = """
I couldn't find any existing insights matching your request, and I wasn't able to create new ones.

Please try:
- Being more specific about what metrics or events you want to track
- Checking if you have the necessary permissions to create insights
- Trying again with a different query
"""
