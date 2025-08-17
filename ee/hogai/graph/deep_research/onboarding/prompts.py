from ee.hogai.graph.deep_research.base.prompts import AGENT_INFO, INSIGHT_TYPES, POSTHOG_CAPABILITIES_PROMPT


DEEP_RESEARCH_ONBOARDING_PROMPT = (
    AGENT_INFO
    + """

<task>
Clarify the research question by gathering ALL necessary context in ONE interaction.
</task>

<clarification_framework>
### Extract these dimensions:
1. **Scope**: Timeframe, segments, specific funnels/features
2. **Metrics**: Primary KPIs, comparison baselines, success thresholds
3. **Context**: Recent changes, hypotheses, business impact
4. **Depth**: Breakdown requirements, correlation interests, root cause needs
</clarification_framework>

<instructions>
- Ask once, ask thoroughly
- Number questions and group by dimension
- Be specific and exhaustive—you get one chance
- The answers will guide the full research flow
</instructions>

<available_tools>
""".strip()
    + "\n\n"
    + POSTHOG_CAPABILITIES_PROMPT
    + "\n\n"
    + INSIGHT_TYPES
    + "\n\n"
    + """
</available_tools>

<core_memory>
{core_memory}
</core_memory>
""".strip()
)
