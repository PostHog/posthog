CORE_MEMORY_PROMPT = """
You have access to the core memory about the user's company and product in the <core_memory> tag. Use this memory in your thinking.
<core_memory>
{{{core_memory}}}
</core_memory>
""".strip()
