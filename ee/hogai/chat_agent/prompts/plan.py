from ee.hogai.core.plan_mode import ONBOARDING_TASK_PROMPT, PLAN_MODE_PROMPT_TEMPLATE, PLANNING_TASK_PROMPT

CHAT_PLAN_AGENT_PROMPT = """
{{{role}}}

{{{plan_mode}}}

{{{tone_and_style}}}

{{{writing_style}}}

{{{basic_functionality}}}

{{{switching_modes}}}

{{{task_management}}}

{{{onboarding_task}}}

{{{planning_task}}}

{{{switch_to_execution}}}

{{{tool_usage_policy}}}

{{{billing_context}}}

{{{groups_prompt}}}
""".strip()

CHAT_PLAN_MODE_PROMPT = PLAN_MODE_PROMPT_TEMPLATE.format(
    task_type="product management",
    notebook_type="plan",
    next_step_instruction="Get user approval, then switch to `execution` mode using switch_mode to proceed with the actual task",
    task_type_short="task",
)

# Re-export for convenience
CHAT_ONBOARDING_TASK_PROMPT = ONBOARDING_TASK_PROMPT
CHAT_PLANNING_TASK_PROMPT = PLANNING_TASK_PROMPT

SWITCHING_TO_EXECUTION_PROMPT = """
<execution_mode>
Once the user has approved the plan, switch to `execution` mode using switch_mode to proceed with the actual task.
</execution_mode>
"""

SWITCHING_TO_PLAN_PROMPT = """
<plan_mode>
Switch to `plan` mode using switch_mode to plan a complex task that requires multiple steps and approvals. Getting user approval on your approach before executing prevents wasted effort and ensures alignment.

## When to switch to plan mode

Use plan mode proactively when ANY of these conditions apply:

1. **Multi-step analysis**: The task requires investigating multiple metrics, funnels, or data sources
   - Example: "Why did our conversion rate drop last week?"
   - Example: "Help me understand our user retention patterns"

2. **Complex feature setup**:  Setting up features with multiple components or configurations
   - Example: "Build a dashboard to track our product-market fit metrics"
   - Example: "Create a weekly executive dashboard reporting on user engagement"

3. **Investigation or debugging**: Diagnosing issues that require exploring multiple hypotheses
   - Example: "Our signup funnel is broken somewhere, help me find where"
   - Example: "Figure out why session recordings show errors for some users"

4. **Strategic analysis**: Tasks requiring research, comparison, or recommendations
   - Example: "Compare our mobile vs desktop user behavior"
   - Example: "Which features should we prioritize based on usage data?"

5. **User frustration**: Redoing a task that the user is frustrated with
   - Example: "I'm frustrated with the way our users are interacting with the product, help me understand why"

## When NOT to use plan mode

Skip plan mode for simple, single-step tasks:
- "Show me pageviews for the last 7 days"
- "How many users signed up yesterday?"
- "What's our current conversion rate?"
- "Create a simple event trend chart"

## Examples

<example>
User: "Why did our activation rate drop by 15% this month?"
Action: Switch to plan mode - requires investigating multiple metrics, comparing time periods, and exploring hypotheses.
</example>

<example>
User: "Help me set up cohort analysis to track user retention by signup source"
Action: Switch to plan mode - requires understanding data structure, creating cohorts, and building multiple visualizations.
</example>

<example>
User: "Show me the trend for $pageview events"
Action: Stay in current mode - simple query that can be answered directly.
</example>

<example>
User: "I want to understand why users are churning after the trial period"
Action: Switch to plan mode - open-ended investigation requiring multiple analyses and user approval on approach.
</example>
</plan_mode>
"""
