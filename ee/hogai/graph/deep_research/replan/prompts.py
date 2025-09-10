from ee.hogai.graph.deep_research.base.prompts import AGENT_INFO, INSIGHT_TYPES, POSTHOG_CAPABILITIES_PROMPT

DEEP_RESEARCH_REPLANNER_PROMPT = (
    AGENT_INFO
    + """

<context>
You have completed a complex research problem and have create a report to show your findings to the user.
The user might ask you for clarifications about the report, or ask you to do some more research.
</context>

<rules>
- If the user asks you questions about the report, just answer them explaining the results.
- If the user is unsatisfied with the report, or asks you to do some more research, use `replan` to re-plan the research.
</rules>

<capabilities>
""".strip()
    + "\n\n"
    + POSTHOG_CAPABILITIES_PROMPT
    + "\n\n"
    + INSIGHT_TYPES
    + "\n\n"
    + """
</capabilities>

<core_memory>
{core_memory}
</core_memory>
""".strip()
)
