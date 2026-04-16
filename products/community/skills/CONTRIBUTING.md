# Contributing a community skill

Community skills are markdown guides that teach AI agents how to accomplish a specific job in PostHog (for example: "audit inactive cohorts", "set up a funnel from recent pageviews", "triage error tracking alerts"). They're distributed through PostHog's skills registry and consumed by the MCP server, coding agents, and third-party tooling.

This guide walks through creating, validating, and submitting a skill.

## 1. What makes a good skill

A skill is a **job-to-be-done template** — it answers "how do I accomplish X with PostHog?", not "what does tool Y do?". If you find yourself listing every argument a PostHog API accepts, you're probably documenting a tool. A skill should describe an outcome, the relevant tools, and the workflow that ties them together.

Good skill candidates:

- Repetitive PostHog workflows that take multiple tool calls
- Analysis patterns that need context (which events? which filters?)
- Maintenance tasks (cleanup, auditing, migration)

Less good:

- Single-tool wrappers (the tool description already covers that)
- Opinionated tutorials that don't generalize
- Anything that hardcodes credentials, URLs, or project IDs

## 2. Create the skill

```bash
bin/hogli init:skill --product community --name <your-skill-name>
```

This scaffolds `products/community/skills/<your-skill-name>/SKILL.md` with the required frontmatter and a template body.

Alternatively, copy `.template/SKILL.md` manually — then rename the directory to your skill name (`lowercase-kebab-case`, 3-64 characters).

### Frontmatter requirements

The generated frontmatter looks like:

```yaml
---
name: your-skill-name # lowercase-kebab-case, 3-64 chars, must match directory
description: >- # 20-1024 chars — when to use, what it does
  Audit inactive surveys across a PostHog project and recommend ones
  safe to archive. Use when the user wants to clean up survey clutter.
version: 0.1.0 # semver, bump on meaningful content changes
category: surveys # one of the registry categories (see schema below)
source: community # must be "community" for skills in this directory
tags: [audit, cleanup] # up to 8 free-form tags for discovery
products: [surveys] # which PostHog products this skill touches
author: your-github-handle # optional, how you'd like to be credited
requires_scopes: [survey:read] # MCP scopes the agent needs
---
```

Valid categories: `analytics`, `flags`, `experiments`, `replay`, `errors`, `llm`, `surveys`, `workflows`, `data-warehouse`, `other`.

## 3. Allowed content

Community skills are markdown-only. At build time, the following are rejected:

- A `scripts/` directory
- Any `.j2` Jinja2 template (including `SKILL.md.j2`)
- Binary files

You can include markdown reference pages under `references/` if your skill is long enough to benefit from progressive disclosure:

```text
products/community/skills/your-skill-name/
├── SKILL.md            # Entry point (required)
└── references/         # Optional
    ├── details.md
    └── examples.md
```

If you need capabilities beyond markdown (live Pydantic schema rendering, dynamic examples), the skill probably belongs in `products/<product>/skills/` — reach out in the PR and we'll help you find the right home.

## 4. Validate locally

Fast syntax check (no Django or database needed):

```bash
bin/hogli lint:skills
```

This catches: missing frontmatter, name/description schema violations, use of disallowed `.j2`/`scripts/` in a community skill, duplicate skill names across the whole repo.

Full build + local install for testing with Claude Code or another MCP-aware agent:

```bash
bin/hogli sync:skill -- --name your-skill-name
```

This renders the skill and copies it to `.agents/skills/your-skill-name/`, where Claude Code and compatible agents pick it up automatically.

## 5. Open a PR

- Keep the PR focused: one skill per PR, no unrelated changes.
- Paste the [safety checklist](#safety-checklist) below into your PR description so reviewers can walk through it with you.
- The `Agent Skills` CI job (`.github/workflows/ci-agent-skills.yml`) runs `hogli lint:skills` + `hogli build:skills` on every PR. Reviewers from `@PostHog/team-devex` will be auto-assigned via `CODEOWNERS-soft`.

## 6. What happens after merge

- On merge to `master`, CI rebuilds the skill archive and publishes:
  - A versioned release: `agent-skills-v0.N.0` (bumped automatically)
  - The rolling `agent-skills-latest` release
- Your skill appears in `skills-index.json` on the next release and is immediately available to every agent that consumes the registry.
- Renaming a skill after release is a breaking change for consumers — bump the `version` field and open a new PR explaining the rename.

## Safety checklist

By contributing a skill, you agree that:

- [ ] It contains no secrets, API keys, or other credentials
- [ ] It does not include prompt-injection payloads designed to subvert agent behavior
- [ ] All URLs point to `posthog.com`, `github.com/PostHog`, or other well-known public sources
- [ ] Any instructions to write or delete PostHog data clearly call out the destructive nature and require user confirmation
- [ ] The `description` accurately reflects what the skill does — it's the primary signal agents use to decide when to run it

Reviewers will reject contributions that fail these checks. Repeat or malicious violations may result in the contributor being blocked from future submissions.
