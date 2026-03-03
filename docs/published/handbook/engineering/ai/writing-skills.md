# Writing skills

Skills are job-to-be-done templates that teach agents _how_ to use capabilities to achieve a goal.
They should read like how an experienced person would approach a job,
not like a rigid script of commands to run.
Describe the workflow, the reasoning behind each step, and what to watch out for –
then trust the agent to adapt.
Overly strict instructions break when context changes;
a well-explained approach generalizes.

This page covers what skills are, how to write them, and how the build pipeline works.
For adding MCP tools (the capabilities themselves), see [Adding tools to the MCP server](/handbook/engineering/ai/implementing-mcp-tools).

## TL;DR

```sh
# 1. Scaffold a new skill in your product
hogli init:skill

# 2. Write your skill in products/{product}/skills/{skill-name}/SKILL.md
#    Add references/ for detailed content, use .md.j2 for templates

# 3. Lint (fast, no Django needed)
hogli lint:skills

# 4. Build locally to verify rendered output
hogli build:skills

# 5. Merge to master – CI builds and distributes automatically
```

## Skills vs tools

**Tools** are atomic capabilities – CRUD operations and simple actions exposed via the MCP server.
They answer "what can I do?" (list feature flags, execute SQL, create a survey).

**Skills** answer "how do I accomplish X?"
They combine tools, domain knowledge, query patterns, and step-by-step workflows
into a template that agents follow to solve a class of problems.

A skill might reference multiple tools, include HogQL query examples,
explain what data to verify before querying,
and describe the desired outcome for the customer.

This separation matters because agents are good at composing simple tools
but need guidance on _which_ tools to use, in _what order_, with _what constraints_.

## Skill structure

Skills live in `products/*/skills/` and come in two forms.
If your product hasn't moved to the `products/` folder yet,
create a product folder and add skills there –
skills are designed to work from within the products folder structure.

### Simple skill (single file)

```text
products/{product}/skills/
    analyzing-llm-traces.md          # or .md.j2 for Jinja2 templates
```

The skill name is the filename stem.

### Directory skill (with references)

```text
products/{product}/skills/{skill-name}/
    SKILL.md                         # entry point (required)
    references/                      # optional, collected recursively
        guidelines.md
        models-actions.md
        example-trends.md.j2
    scripts/                         # optional, collected recursively
        setup.sh
```

The skill name is the directory name.
Only `references/` and `scripts/` subdirectories are included in the output –
other subdirectories are ignored.

### Frontmatter

Every skill entry point must have YAML frontmatter with `name` and `description`:

```yaml
---
name: query-examples
description: 'HogQL query examples and reference material for PostHog data. Read when writing SQL queries...'
---
```

Both fields are required and validated at build time.

### Progressive disclosure

`SKILL.md` serves as an overview that points agents to detailed materials as needed.
Reference files are loaded on demand – only the entry point is read initially.
Keep `SKILL.md` under 500 lines and split detailed content into `references/`.

See [`query-examples/SKILL.md`](https://github.com/PostHog/posthog/blob/master/products/posthog_ai/skills/query-examples/SKILL.md)
for how this works in practice –
the entry point links to 30+ reference files
covering model schemas, query patterns, and HogQL extensions.

## Naming and description guidelines

Follow [Anthropic's skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices).
Key points are summarized below.

### Naming conventions

Use lowercase kebab-case. Prefer gerund form (verb + -ing):

| Pattern                   | Examples                                                                  |
| ------------------------- | ------------------------------------------------------------------------- |
| Gerund form (preferred)   | `analyzing-llm-traces`, `writing-hogql-queries`, `managing-feature-flags` |
| Noun phrases (acceptable) | `query-examples`, `error-tracking-guide`                                  |

Skills **must not** be prefixed with `posthog-*`.
The `posthog-` prefix is added automatically depending on the consumer agent.

Skills also **must not** contain the reserved words `anthropic` or `claude` in the name.

The `name` field: lowercase letters, numbers, and hyphens only. Max 64 characters.

### Writing descriptions

The `description` field is critical for skill discovery –
agents use it to decide which skill to activate from potentially many available skills.
Max 1024 characters.

**Rules:**

- Write in **third person** ("Analyzes LLM traces...", not "I can help you analyze...").
- Include both **what** the skill does and **when** to use it.
- Be specific – include key terms agents would match against.

**Good descriptions:**

```yaml
# Specific, includes triggers and key terms
description: >
  HogQL query examples and reference material for PostHog data.
  Read when writing SQL queries to find patterns for analytics
  (trends, funnels, retention, lifecycle, paths, stickiness,
  web analytics, error tracking, logs, sessions, LLM traces)
  and system data (insights, dashboards, cohorts, feature flags,
  experiments, surveys, data warehouse).

description: >
  Step-by-step guide for analyzing LLM traces in PostHog.
  Use when inspecting AI generation latency, token usage,
  human feedback, or trace hierarchies.
```

**Bad descriptions:**

```yaml
# Too vague – agents can't determine when to use it
description: 'Helps with LLM analytics'

# Too broad – an umbrella for everything isn't a skill
description: 'Everything about PostHog AI features'
```

## Good and bad skill examples

### Good: `analyzing-llm-traces`

A focused skill that guides the agent through a specific workflow:

- Starts by verifying that `$ai_trace`, `$ai_generation`, `$ai_feedback` events exist.
- Provides HogQL queries to retrieve trace data with the right properties.
- Explains how to join generations to traces via `$ai_trace_id`.
- Describes the desired outcome (latency analysis, feedback summary, cost breakdown).

The agent knows what tools to use (execute-sql, read-data-schema),
in what order, and what a successful result looks like.

### Good: `query-examples`

A reference skill with a clear entry point and 30+ reference files:

- Entry point ([`SKILL.md`](https://github.com/PostHog/posthog/blob/master/products/posthog_ai/skills/query-examples/SKILL.md))
  links to model schemas, query patterns, and HogQL extensions.
- Guidelines file ([`references/guidelines.md`](https://github.com/PostHog/posthog/blob/master/products/posthog_ai/skills/query-examples/references/guidelines.md))
  explains schema verification workflow, time ranges, joins, and HogQL differences.
- Uses progressive disclosure – agents load only the references they need.

### Bad: `llm-analytics`

An umbrella skill that tries to cover everything:
traces, experiments, evaluations, cost tracking, prompt management.
Too broad to be useful – agents can't determine _when_ to activate it
and the instructions are too generic to guide any specific workflow.
Break it into focused skills instead.

### Bad: poor descriptions

```yaml
# Name is vague
name: helper
description: 'Helps with stuff'

# Name uses reserved prefix
name: posthog-queries
description: 'Query helper'
```

## Template engine

Skills support [Jinja2](https://jinja.palletsprojects.com/) templates.
Any file ending in `.j2` is rendered at build time,
and the `.j2` suffix is stripped from the output path.
Plain `.md` files pass through unchanged.

The Jinja2 environment uses `StrictUndefined` (undefined variables raise errors),
`lstrip_blocks`, and `trim_blocks` for clean whitespace handling.

### Built-in template functions

Three global functions are available in all `.j2` templates:

#### `pydantic_schema(dotted_path, indent=2)`

Imports a Pydantic model by its fully-qualified path and returns its JSON Schema:

```jinja2
{{ pydantic_schema("products.feature_flags.backend.max_tools.FeatureFlagCreationSchema") }}
```

Changes to the Pydantic model automatically update the skill output on the next build.

#### `render_hogql_example(query_dict)`

Takes a PostHog query spec and renders it to HogQL SQL:

```jinja2
{{ render_hogql_example({"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}], "dateRange": {"date_from": "-7d"}}) }}
```

Time is frozen to `2025-12-10T00:00:00` for deterministic output.

#### `hogql_functions()`

Returns a sorted list of all public HogQL function names:

```jinja2
{% for fn in hogql_functions() %}
{{ fn }}
{% endfor %}
```

### Extending the template engine

The build pipeline should be extended so the monorepo remains the source of truth
for all skill content.
When domain knowledge lives in code (Pydantic models, query runners, function registries),
add a template function to extract it at build time
rather than duplicating it as static markdown that drifts.

To add a new template function:

1. Create a module under `products/posthog_ai/scripts/`
   (follow existing patterns like `pydantic_schema/`, `hogql_example/`).
2. Register it in `SkillRenderer.__init__()`
   by adding to `self.env.globals` via `_create_jinja_env(**extra_globals)`.

## Build pipeline

The pipeline discovers, renders, and packages skills.
Source of truth: [`products/posthog_ai/scripts/build_skills.py`](https://github.com/PostHog/posthog/blob/master/products/posthog_ai/scripts/build_skills.py).

### Pipeline steps

```text
Discovery     Scan products/*/skills/ for skills (loose files or directories with SKILL.md)
    │
    ▼
Rendering     Render .j2 files through Jinja2, pass .md files through unchanged
    │
    ▼
Building      Collect entry point + references/scripts into SkillResource with frontmatter metadata
    │
    ▼
Output        Write to dist/skills/{skill-name}/ and package into dist/skills.zip
```

### CLI commands

```sh
hogli build:skills          # Build all skills and create dist/skills.zip
hogli build:skills --list   # List discovered skills without building
hogli lint:skills           # Validate skill sources (no Django required)
hogli init:skill            # Scaffold a new skill directory
```

`lint:skills` validates syntax, frontmatter, binary file detection, and duplicate names.
It runs without Django, so it's fast in CI.

`build:skills` requires the full Python environment
because template functions import Django models and Pydantic schemas.

### Output

Built skills are written to `products/posthog_ai/dist/skills/` (gitignored)
and packaged into `dist/skills.zip` with deterministic timestamps for reproducible builds.

## Distribution

Distribution is automatic.
Built skills are published through the [posthog/skills](https://github.com/PostHog/skills) repo
and consumed via plugins for coding agents at [PostHog/ai-plugin](https://github.com/PostHog/ai-plugin).

PostHog Code already consumes skills automatically.
PostHog AI will consume the same set of skills.

Product teams don't need to handle distribution –
the pipeline and CI take care of it.

## Testing

See [How to develop and test](/handbook/engineering/ai/implementation#how-to-develop-and-test)
for instructions on running the MCP server locally and verifying skills end-to-end.

## Writing effective skills

The context window is a shared resource.
Your skill competes with the system prompt, conversation history, other skills, and the user's request.

**Default assumption:** the agent is already very smart.
Only include context it doesn't already have.
Challenge each piece of information: does the agent really need this explanation?

See [Anthropic's full best practices guide](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
for detailed advice on progressive disclosure, feedback loops, workflows, and evaluation-driven development.
