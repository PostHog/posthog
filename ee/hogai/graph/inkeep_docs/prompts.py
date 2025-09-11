INKEEP_DATA_CONTINUATION_PHRASE = "Now, let's get to your data request"

INKEEP_DOCS_SYSTEM_PROMPT = (
    "If the user has requested a query on analytics data (aka an insight) in their latest message, "
    f"""you MUST append "{INKEEP_DATA_CONTINUATION_PHRASE}: <brief query description>" to the end of your response."""
)
