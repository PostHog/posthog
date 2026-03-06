---
name: writing-skills
description: 'Guide for writing PostHog agent skills — job-to-be-done templates that teach agents how to use MCP tools to achieve a goal. Use when adding new product functionality that agents should know how to work with, creating a new skill, or updating existing skills in products/*/skills/.'
---

# Writing skills for PostHog agents

Read the full guide at [docs/published/handbook/engineering/ai/writing-skills.md](docs/published/handbook/engineering/ai/writing-skills.md).

## Quick workflow

```sh
# 1. Scaffold
hogli init:skill

# 2. Write your skill in products/{product}/skills/{skill-name}/SKILL.md

# 3. Lint
hogli lint:skills

# 4. Build to verify
hogli build:skills
```

Distribution is automatic after merge — CI publishes to [PostHog/skills](https://github.com/PostHog/skills).

## When to write a skill

When new functionality is added to a product and agents need to know how to work with it.
A skill is not about what tools exist (that's the MCP server) —
it's about how an experienced person would approach a job using those tools.

Ask: "If a customer asked an agent to do X with my feature, would the agent know the right approach?"
If not, write a skill.

## Key rules

- **Name**: lowercase kebab-case, prefer gerund form (`analyzing-llm-traces`, not `llm-analytics`). Never prefix with `posthog-*`.
- **Description**: third person, specific, include trigger terms and when to use it. Max 1024 chars.
- **Structure**: `SKILL.md` entry point + `references/` for detailed content. Keep `SKILL.md` under 500 lines.
- **Frontmatter**: `name` and `description` are required.
- **Tone**: describe the workflow and reasoning, not a rigid script. Trust the agent to adapt.
- **Conciseness**: the agent is smart — only include context it doesn't already have.

## Skill structure

```text
products/{product}/skills/{skill-name}/
    SKILL.md                         # entry point (required)
    references/                      # optional
        guidelines.md
        models-foo.md
        example-bar.md.j2            # Jinja2 template, rendered at build time
    scripts/                         # optional
        setup.sh
```

Only `references/` and `scripts/` subdirectories are collected. Others are ignored.

## Template functions

Files ending in `.j2` are rendered with Jinja2 at build time
by [`products/posthog_ai/scripts/build_skills.py`](products/posthog_ai/scripts/build_skills.py).
Extend the build pipeline so the monorepo stays the source of truth —
when domain knowledge lives in code (Pydantic models, query runners, function registries),
add a template function rather than duplicating it as static markdown that drifts.

Available functions:

- `pydantic_schema("dotted.path.to.Model")` — renders a Pydantic model's JSON Schema
- `render_hogql_example({"kind": "TrendsQuery", ...})` — renders a query spec to HogQL SQL
- `hogql_functions()` — returns all available HogQL function names

## Good example: `query-examples`

- Clear entry point linking to 30+ reference files
- Progressive disclosure — agents load only what they need
- Mix of static `.md` and generated `.md.j2` content
- See [`products/posthog_ai/skills/query-examples/SKILL.md`](products/posthog_ai/skills/query-examples/SKILL.md)

## Bad example: `llm-analytics`

An umbrella skill covering traces, experiments, evaluations, cost tracking, prompt management.
Too broad — agents can't determine when to activate it. Break into focused skills instead.
