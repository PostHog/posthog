---
name: growing-dev-knowledge-graph
description: >
  Adds a learning to the dev knowledge graph (tools/dev-knowledge-graph) — markdown knowledge nodes connected to the software modules, products, and properties they are about, and to the skills that encode them.
  Use when finishing a piece of work that taught something worth keeping, when the user says "add this to the knowledge graph" or "record this learning", or when the same problem class has now come up more than once.
  Also covers regenerating and viewing the graph, and when a learning should graduate into a real skill.
---

# Growing the dev knowledge graph

`tools/dev-knowledge-graph/` holds a knowledge-first graph of how we work: **learning** nodes carry inspectable markdown (PRs and conversations appear as links inside it, not as nodes) and connect to the software **modules**, **products**, and **properties** they are about, plus the **skills** (existing or proposed) that encode them.
The graph only grows if we feed it — that is this skill's job.

## When to add a learning

Add one when work produced knowledge that outlives the conversation:

- The same class of problem has now appeared **more than once** (the strongest signal — cite both occurrences as evidence).
- A workflow was re-explained from scratch that clearly repeats.
- A non-obvious constraint was discovered the hard way (a limit, a race, a tooling behavior).

Do **not** add: one-off fixes, anything the repo already records (CLAUDE.md, docs, code comments), or restatements of an existing learning — extend that learning's evidence instead.

## How to add one

1. Read `tools/dev-knowledge-graph/learnings.json` and check for an existing learning that covers the insight. If found, extend its `markdown` and `evidence_tasks` instead of duplicating.
2. Append a new entry:

   ```json
   {
     "id": "short-kebab-slug",
     "title": "One-line statement of the learning",
     "markdown": "The why, with enough detail that a stranger gets it. Link context: [#66590](https://github.com/PostHog/posthog/pull/66590).",
     "modules": ["frontend/src/lib/components/TaxonomicFilter"],
     "products": ["product analytics"],
     "properties": [],
     "evidence_tasks": [12345],
     "skills": [{ "name": "some-skill", "status": "proposed" }],
     "author": "your-name"
   }
   ```

   - `markdown` is the knowledge itself. PRs, issues, and docs are **context, not knowledge** — put them in the markdown as links, never as their own nodes.
   - `modules` / `products` / `properties` are the system entities the learning is about — software module paths, product names (sentence case), and user/event properties. Reuse labels already in `learnings.json` where they fit, so knowledge clusters instead of fragmenting.
   - `evidence_tasks`: PostHog Code task numbers of the conversations that taught this (shown as an overlay with `--include-conversations`).
   - `skills`: link the skill that encodes (status `existing`) or should encode (status `proposed`) the learning. Proposed entries are the shared backlog of skills worth writing.
   - `author`: your short name, consistent across entries — it powers the viewer's per-user filter. Match the local part of your email so your conversations and learnings share one identity.

3. **Public-repo safety**: `learnings.json` is committed to a public repository. No customer names, private operational scale, Slack quotes, or unreleased roadmap details. Qualitative descriptions and public PR numbers are fine.
4. Regenerate to verify it parses and links:

   ```bash
   python3 tools/dev-knowledge-graph/ingest.py
   ```

   Never commit `out/` — fetched conversation content is private and the directory is gitignored.

## When a learning should graduate

A `proposed` skill attached to a learning with **3+ evidence tasks** is ready to write for real — follow `writing-skills`, then flip its `status` to `existing` here.
If a learning describes a mechanically checkable convention, prefer the automation ladder (linter > lint-staged > skill > instructions) and say so in the body.
