---
name: growing-dev-knowledge-graph
description: >
  Adds a learning to the dev knowledge graph (tools/dev-knowledge-graph) — the graph of agent conversations, PRs, themes, learnings, and the skills that encode them.
  Use when finishing a piece of work that taught something worth keeping, when the user says "add this to the knowledge graph" or "record this learning", or when the same problem class has now come up more than once.
  Also covers regenerating and viewing the graph, and when a learning should graduate into a real skill.
---

# Growing the dev knowledge graph

`tools/dev-knowledge-graph/` holds a graph of how we work: conversations (PostHog Code tasks) link to the PRs they touched and the themes they belong to, and a curated layer of **learnings** links evidence to the **skills** (existing or proposed) that should encode it.
The curated layer only grows if we feed it — that is this skill's job.

## When to add a learning

Add one when work produced knowledge that outlives the conversation:

- The same class of problem has now appeared **more than once** (the strongest signal — cite both occurrences as evidence).
- A workflow was re-explained from scratch that clearly repeats.
- A non-obvious constraint was discovered the hard way (a limit, a race, a tooling behavior).

Do **not** add: one-off fixes, anything the repo already records (CLAUDE.md, docs, code comments), or restatements of an existing learning — extend that learning's evidence instead.

## How to add one

1. Read `tools/dev-knowledge-graph/learnings.json` and check for an existing learning that covers the insight. If found, append your task number to its `evidence_tasks` and stop.
2. Append a new entry:

   ```json
   {
     "id": "short-kebab-slug",
     "title": "One-line statement of the learning",
     "body": "The why, with enough detail that a stranger gets it. Cite PRs by number.",
     "themes": ["existing-theme-key"],
     "evidence_tasks": [12345],
     "skills": [{ "name": "some-skill", "status": "proposed" }],
     "author": "your-name"
   }
   ```

   - `themes`: prefer keys already in `THEME_RULES` in `ingest.py`; a new theme key is allowed and becomes a node automatically.
   - `evidence_tasks`: PostHog Code task numbers of the conversations that taught this.
   - `skills`: link the skill that encodes (status `existing`) or should encode (status `proposed`) the learning. Proposed entries are the shared backlog of skills worth writing.
   - `author`: your short name, consistent across entries — it powers the viewer's per-user filter. Match the local part of your email so your tasks and learnings share one identity.

3. **Public-repo safety**: `learnings.json` is committed to a public repository. No customer names, private operational scale, Slack quotes, or unreleased roadmap details. Qualitative descriptions and public PR numbers are fine.
4. Regenerate to verify it parses and links:

   ```bash
   python3 tools/dev-knowledge-graph/ingest.py --from-file tools/dev-knowledge-graph/out/tasks.json
   ```

   (or with `POSTHOG_PERSONAL_API_KEY` set, drop `--from-file` to refresh tasks too; add `--all-users` for the team-wide graph). Never commit `out/` — it contains private conversation content and is gitignored.

## When a learning should graduate

A `proposed` skill attached to a learning with **3+ evidence tasks** is ready to write for real — follow `writing-skills`, then flip its `status` to `existing` here.
If a learning describes a mechanically checkable convention, prefer the automation ladder (linter > lint-staged > skill > instructions) and say so in the body.
