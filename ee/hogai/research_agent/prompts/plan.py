from ee.hogai.core.plan_mode import PLAN_MODE_PROMPT_TEMPLATE

PLAN_AGENT_PROMPT = """
{{{role}}}

{{{plan_mode}}}

{{{tone_and_style}}}

{{{writing_style}}}

{{{basic_functionality}}}

{{{switching_modes}}}

{{{task_management}}}

{{{onboarding_task}}}

{{{planning_task}}}

{{{switch_to_research_mode}}}

{{{tool_usage_policy}}}

{{{billing_context}}}

{{{groups}}}
""".strip()

PLAN_MODE_PROMPT = PLAN_MODE_PROMPT_TEMPLATE.format(
    task_type="research",
    notebook_type="research plan",
    next_step_instruction="Get user approval, then switch to `research` mode using switch_mode to proceed with the actual research",
    task_type_short="research",
)

SWITCHING_TO_RESEARCH_MODE_PROMPT = """
<research_mode>
Once the user has approved the plan, switch to `research` mode to proceed with the actual research to answer the user's questions.
</research_mode>
"""
