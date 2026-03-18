# LLM prompting guide for PostHog

You know code, now meet prompts. This guide explains how we make effective LLM prompts in PostHog's AI features.

## Standard building blocks

Always use `MaxChatOpenAI` instead of plain LangChain `ChatOpenAI`:

```python
from ee.hogai.llm import MaxChatOpenAI

# ✅ Correct - auto-injects user/project/org context
llm = MaxChatOpenAI(user=user, team=team, model="gpt-4.1")

# ❌ Wrong - missing PostHog context
llm = ChatOpenAI(model="gpt-4.1")
```

`MaxChatOpenAI` automatically injects context into every prompt:

- Project name and timezone
- Organization name
- User name and email
- Current project datetime

This context appears at the end of system messages.

## The anatomy of a PostHog prompt

PostHog prompts typically follow a structure like this:

```python
SYSTEM_PROMPT = """
<agent_info>
You are PostHog's AI agent...
Your role and personality description.
</agent_info>

<instructions>
Specific task instructions and guidelines.
</instructions>

<constraints>
What the agent should and shouldn't do.
</constraints>

<examples>
Few-shot examples demonstrating the expected behavior.
</examples>

{{{dynamic_context}}}
""".strip()
```

As you see, we use non-nested XML tags to clearly delineate sections.

### Variable templating with Mustache

PostHog uses Mustache templating for dynamic content:

```python
# Basic variable substitution
"The project name is {{{project_name}}}"

# Conditional sections
"{{#show_advanced}}Advanced options: {{{options}}}{{/show_advanced}}"

# Lists/iterations
"{{#events}}Event: {{{name}}}{{/events}}"
```

## Writing prompts that work

### Specificity

```python
# ✅ Good - specific and actionable
"""Generate a trends query that shows daily active users for the last 30 days, filtered to exclude internal users, displayed as a line chart."""

# ❌ Bad - vague and ambiguous
"""Create a user trend analysis."""
```

### Context and constraints

```python
# ✅ Good - includes constraints and context
"""
Act as an expert product analyst. Generate a JSON schema for funnel insights.
- Only use events and properties provided in the taxonomy
- Filter internal users by default
- Use reasonable date ranges when not specified
- Return valid JSON that matches the schema exactly
"""

# ❌ Bad - no constraints or context
"""Create a funnel query."""
```

### Few-shot examples

Effective examples show input-output pairs that demonstrate edge cases:

```python
EXAMPLES = """
### Example 1: Simple conversion rate
Question: What's the signup to purchase conversion rate?
Output:
{"kind":"FunnelsQuery","series":[{"event":"user signed up"},{"event":"purchase"}]}

### Example 2: With filters and breakdown
Question: Conversion rate by country for mobile users?
Output:
{"kind":"FunnelsQuery","series":[{"event":"user signed up","properties":[{"key":"$device_type","value":"Mobile"}]},{"event":"purchase"}],"breakdownFilter":{"breakdown":"$geoip_country_name"}}
"""
```

### Guarding against ambiguity

```python
"""
If the user's question is ambiguous:
- Ask for clarification using the `foo` tool
- Don't make assumptions about missing parameters
- Suggest common alternatives: "Did you mean daily active users or total events?"
"""
```

## Architectural patterns

Different prompts for different problems.

### Single-call tasks

For specialized tasks (query generation, summarization, etc.):

```python
QUERY_GENERATOR_PROMPT = """
Act as an expert product analyst. Your task is to generate JSON schemas for PostHog insights.

<role_context>
You understand PostHog's event tracking, user properties, and analytics concepts.
You know the difference between trends, funnels, and retention queries.
</role_context>

<task_instructions>
1. Analyze the user's natural language query
2. Determine the appropriate insight type (trends/funnel/retention)
3. Generate valid JSON matching the schema
4. Apply sensible defaults for missing parameters
</task_instructions>

<schema_definitions>
{{{schema_examples}}}
</schema_definitions>
"""
```

```python
SUMMARIZER_PROMPT = """
Summarize this PostHog action in maximum three sentences.

Actions contain filters that users create to track specific behaviors:
- Multiple match groups combined with OR
- Filters within groups combined with AND
- Include autocaptured events ($autocapture) and custom events

Focus on:
- What user behavior this action captures
- Key filters that define the action
- Business context when clear from the action name

Don't repeat technical jargon - explain in business terms.
"""
```

### Multi-call tasks

When you let an LLM call tools and use their results, you get an agent:

```python
TOOL_AGENT_PROMPT = """
You have access to these tools:
1. `search_events` - Find events matching patterns
2. `get_property_values` - Get possible values for properties
3. `final_answer` - Provide the final query plan

Before generating a query:
- Use search_events to find relevant events
- Use get_property_values to validate filter values
- Call final_answer with your complete plan

Never guess event names or property values - always verify using tools.
"""
```

## Performance and costs

We use prompt caching on system prompts to save on costs, and improve latency.
Put dynamic content at the end of system prompts so that OpenAI's prompt caching is effective:

```python
# ✅ Good - static content first, dynamic last
SYSTEM_PROMPT = """
You are an expert analyst...

<static_instructions>
These instructions never change...
</static_instructions>

<examples>
Static examples...
</examples>

{{{dynamic_user_context}}}
{{{current_data}}}
""".strip()

# ❌ Bad - dynamic content breaks caching
SYSTEM_PROMPT = """
Current user: {{{user_name}}}
Current project: {{{project_name}}}

You are an expert analyst...
<static_content>
""".strip()
```

## Evaluation

PostHog uses Braintrust to test AI effectiveness. See `ee/hogai/eval/` for examples, and implement new ones for the use case you're working on.

For expert feedback, tag `@team-posthog-ai` on LLM-related PRs! Before doing that, test your feature with various user prompts, especially tricky ones.

### More resources

- [GPT-4.1 prompting guide](https://cookbook.openai.com/examples/gpt4-1_prompting_guide) - general best practices
- [o3/o4-mini prompting guide](https://cookbook.openai.com/examples/o-series/o3o4-mini_prompting_guide) - tool-calling with reasoning models
