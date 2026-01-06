DASHBOARD_CREATION_ERROR_MESSAGE = """
I encountered an issue while creating the dashboard. Please try again.
"""

DASHBOARD_EDIT_ERROR_MESSAGE = """
I encountered an issue while adding insights to the dashboard. Please try again.
"""

DASHBOARD_SUCCESS_MESSAGE_TEMPLATE = """
**Dashboard Created**

The dashboard [{dashboard_name}]({dashboard_url}) was created.
The dashboard contains {insight_count} insight{insight_plural}.

**Included insights**
{insights_list}

"""

DASHBOARD_EDIT_SUCCESS_MESSAGE_TEMPLATE = """
**Dashboard Edited**

The dashboard [{dashboard_name}]({dashboard_url}) was edited successfully.
The dashboard now has {insight_count} insight{insight_plural} added to it.

**Added insights**
{insights_list}

"""
QUERIES_WITHOUT_INSIGHTS_MESSAGE_TEMPLATE = """
**Queries without insights**
Due to issues with creating insights, the following queries were not included in the dashboard:
{queries_without_insights}
"""


DASHBOARD_NO_INSIGHTS_MESSAGE = """
No existing insights matched the user's request and new insights were not able to be created.

From the insight creation process, the message was:

{subgraph_last_message}

"""
