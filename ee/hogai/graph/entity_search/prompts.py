FOUND_ENTITIES_MESSAGE_TEMPLATE = """
Successfully found {total_results} entities matching the user's query.

{entities_list}
"""

ENTITY_TYPE_SUMMARY_TEMPLATE = """
**Results by type:**
{entity_type_summary}
"""

HYPERLINK_USAGE_INSTRUCTIONS = """
\n\nVERY IMPORTANT INSTRUCTIONS: ALWAYS WHEN MENTIONING ANY ENTITY IN YOUR RESPONSE, YOU MUST USE THE HYPERLINK FORMAT PROVIDED ABOVE.
For example, write '[Dashboard name](/project/123/dashboard/dashboard_id)' instead of just 'Dashboard name'.
For every entity, write '[Entity name](/project/123/entity_type/entity_id)' instead of just 'Entity name'.
IF YOU DON'T USE THE HYPERLINK FORMAT, THE USER WILL NOT BE ABLE TO CLICK ON THE ENTITY NAME AND WILL NOT BE ABLE TO ACCESS THE ENTITY.
"""
