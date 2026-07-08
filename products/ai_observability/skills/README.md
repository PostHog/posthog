# AI observability skills

Agent skills for the AI observability product.
Built by `hogli build:skills` and installed into sandbox containers for background agents.
Also available to Claude Code / Codex via `hogli sync:skill`.

## Skills

- **exploring-llm-traces** — how to query, inspect, and debug LLM traces via MCP tools.
  Covers the `$ai_*` event schema, where message content lives (`events` vs the `ai_events`
  table), content detail levels, and step-by-step debugging workflows.
- **exploring-llm-clusters** — how to investigate AI observability clustering results,
  compare cluster behavior, compute metrics, and drill into individual traces.
- **exploring-llm-costs** — how to investigate LLM spend: total cost, breakdowns
  by model/provider/user/trace/custom dimension, token and cache economics,
  cost regressions, and materializing cost insights, dashboards, and alerts.
- **analyzing-expensive-users** — how to analyze the most expensive users in
  AI observability, compare them against baseline usage, inspect
  trace/model/token/cache patterns, and explain what drives their spend.
- **exploring-llm-evaluations** — how to manage and investigate AI observability
  evaluations (`hog`, `llm_judge`, and `sentiment`), run them on specific generations,
  query individual results, and generate AI-powered summaries of pass/fail/N/A patterns for boolean evaluations.

Skills for managing skills themselves (`skills-store`, `working-with-skills`) now live in
the standalone Skills product — see `products/skills/skills/`.

## Adding a new skill

```bash
hogli init:skill -- --product ai_observability --name my-new-skill
```

See `products/posthog_ai/scripts/build_skills.py` for the build pipeline
and `AGENTS.md` for conventions.

## Local testing

```bash
hogli sync:skill -- --name exploring-llm-traces
```

This copies the built skill to `.agents/skills/` for Claude Code to discover.
