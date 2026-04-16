---
title: Contributing community skills
sidebar: Docs
showTitle: true
---

PostHog ships _community skills_ — markdown-only job-to-be-done templates that anyone outside PostHog can contribute. A community skill lives in the PostHog repo, is validated by the same CI that validates official skills, and is distributed through the public skills registry (`skills-index.json`). Any agent that consumes the registry — Claude Code, Cursor, the PostHog MCP server, custom frameworks — picks up community skills automatically once they ship.

This page is the contributor-facing overview. For implementation-level details on the build pipeline and Jinja2 template helpers, see [Writing skills](/handbook/engineering/ai/writing-skills).

## When to contribute a community skill

A community skill is the right fit when you have a PostHog workflow that:

- Takes multiple tool calls and benefits from a canonical walkthrough
- Applies broadly (not hyper-specific to your project)
- Fits in markdown — no code execution, no Pydantic schema introspection, no dynamic content

If you need dynamic rendering (for example, regenerating HogQL examples whenever a Pydantic model changes), the skill belongs in `products/<product>/skills/` and must be owned by a PostHog product team. Open an issue with the proposal instead.

## Where community skills live

```text
products/community/skills/
├── README.md          # Overview
├── CONTRIBUTING.md    # Detailed contribution guide + safety checklist
├── .template/         # Starter scaffold (skipped by the build)
└── <your-skill>/
    ├── SKILL.md       # Required entry point
    └── references/    # Optional markdown-only detail pages
```

Community skills are subject to stricter build rules than official skills:

| Content              | Official skills | Community skills           |
| -------------------- | --------------- | -------------------------- |
| `SKILL.md`           | Required        | Required                   |
| `references/*.md`    | Allowed         | Allowed                    |
| `references/*.md.j2` | Allowed         | **Rejected at build time** |
| `scripts/*`          | Allowed         | **Rejected at build time** |
| `SKILL.md.j2`        | Allowed         | **Rejected at build time** |

Community vs official is determined by location (`products/community/skills/` vs `products/<product>/skills/`) — not by a frontmatter field. Enforcement happens in `products/posthog_ai/scripts/build_skills.py`; `hogli lint:skills` catches violations without needing a Django environment, so contributors get fast feedback in CI.

## Frontmatter schema

Every skill (official or community) has Pydantic-validated frontmatter with just two fields:

```yaml
---
name: your-skill-name # required, lowercase-kebab-case, 3-64 chars, unique across the repo
description: >- # required, 20-1024 chars — agents use this to decide whether to run the skill
  Audit inactive surveys across a PostHog project and recommend ones
  safe to archive.
---
```

This matches the [Anthropic agent skills convention](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview): `description` is the primary trigger signal, so invest in making it specific.

## Distribution

On every merge to master, `.github/workflows/ci-agent-skills.yml` publishes:

1. **`skills.zip`** — the monolithic archive (existing consumers keep working unchanged)
2. **`<skill-name>.zip`** — one zip per skill, so agents can install one skill at a time
3. **`skills-index.json`** — the registry: a small JSON document listing every skill's metadata, archive URL, and SHA-256 checksum

Assets land on two GitHub releases:

- `agent-skills-v0.N.0` — versioned, bumped automatically
- `agent-skills-latest` — the rolling release, always pointing at the most recent master build

The canonical registry URL is:

```text
https://github.com/PostHog/posthog/releases/download/agent-skills-latest/skills-index.json
```

Agents should hit that URL to discover the full skill catalog.

## Using the registry from the MCP server

The PostHog MCP server exposes the registry through two tools:

- `skills-list` — returns metadata for every published skill, with an optional `search` substring filter on name/description
- `skills-get` — returns the full markdown of a named skill, including any `references/*.md` files

Max and any other MCP-aware agent can call `skills-list` at the start of a complex PostHog workflow to check whether a canonical skill exists, then `skills-get` to pull the guidance.

## Review process

Community-skill PRs:

1. Run the `Agent Skills` CI check (`hogli lint:skills` + `hogli build:skills`).
2. Auto-request review from `@PostHog/team-devex` via `CODEOWNERS-soft`.
3. Should include the safety checklist from [`products/community/skills/CONTRIBUTING.md`](https://github.com/PostHog/posthog/blob/master/products/community/skills/CONTRIBUTING.md#safety-checklist) in the PR description.

Reviewers specifically check for: secrets in content, prompt-injection attempts, URLs pointing outside PostHog-owned domains, destructive instructions that skip user confirmation, and misleading descriptions.

## Related

- [Writing skills](/handbook/engineering/ai/writing-skills) — how the build pipeline works and how to write effective skill content
- [Implementing MCP tools](/handbook/engineering/ai/implementing-mcp-tools) — how the tools referenced by skills are exposed to agents
- [Sandboxed agents](/handbook/engineering/ai/sandboxed-agents) — running agents autonomously with scoped OAuth tokens
