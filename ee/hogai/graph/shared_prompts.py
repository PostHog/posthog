CORE_MEMORY_PROMPT = """
You have access to the core memory about the user's company and product in the <core_memory> tag. Use this memory in your thinking.
<core_memory>
{{{core_memory}}}
</core_memory>
""".strip()

HYPERLINK_USAGE_INSTRUCTIONS = """
\n\nVERY IMPORTANT INSTRUCTIONS: ALWAYS WHEN MENTIONING ANY ENTITY IN YOUR RESPONSE, YOU MUST USE THE HYPERLINK FORMAT PROVIDED ABOVE.
For example, write '[Dashboard name](/project/123/dashboard/dashboard_id)' instead of just 'Dashboard name'.
For every entity, write '[Entity name](/project/123/entity_type/entity_id)' instead of just 'Entity name'.
IF YOU DON'T USE THE HYPERLINK FORMAT, THE USER WILL NOT BE ABLE TO CLICK ON THE ENTITY NAME AND WILL NOT BE ABLE TO ACCESS THE ENTITY.
"""
