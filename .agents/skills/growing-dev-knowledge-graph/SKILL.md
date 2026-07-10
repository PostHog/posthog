---
name: growing-dev-knowledge-graph
description: >
  Grows the dev knowledge graph (tools/dev-knowledge-graph) — a drillable mind map of system concepts color-coded by area, with markdown learnings attached to the concepts they taught us about.
  Use when finishing a piece of work that taught something worth keeping, when the user says "add this to the knowledge graph" or "record this learning", when the same problem class has come up more than once, or when the map is missing a part of the system you had to understand to do the work.
  Also covers regenerating and viewing the map, and when a learning should graduate into a real skill.
---

# Growing the dev knowledge graph

`tools/dev-knowledge-graph/` holds a mind map of the system: **concept** nodes are the nouns two people working together would use (the taxonomic filter, the dashboards API, the event pipeline), arranged in a drillable hierarchy and color-coded by system area (layer).
**Learnings** attach to concepts and carry inspectable markdown — PRs and conversations appear as links inside it, never as nodes.
The map exists so someone who didn't do the work can explore what the work taught us, cutting across PRs. It only grows if we feed it.

## When to contribute

Add or extend a **concept** (`concepts.json`) when:

- the map is missing a part of the system you had to understand to do the work
- you learned how data flows through an existing concept and its markdown doesn't say so yet — extend it

Add a **learning** (`learnings.json`) when:

- the same class of problem has now appeared **more than once** (the strongest signal — cite both occurrences)
- a workflow was re-explained from scratch that clearly repeats
- a non-obvious constraint was discovered the hard way (a limit, a race, a tooling behavior)

Do **not** add: one-off fixes, anything the repo already records (CLAUDE.md, docs, code comments), or restatements of an existing learning — extend that learning instead.

**What we did is not what we learned.** A concept describes the system as it is (write in the present tense: "events appear as their own group type", not "we separated the events"). A learning is a memory the work strengthened — often a tension or a worry, not an accomplishment: "adding group types surfaces new data to users _but_ spends the taxonomic filter's complexity budget, and we add more often than we consolidate". If your draft reads like a changelog or a brag, it belongs in the PR description, not the graph.

## How to add a concept

Concepts are the map's skeleton — write the markdown as you'd explain the thing to a teammate: what it is, how data flows through it, which constraints bite.

```json
{
  "id": "recordings-list-query",
  "name": "Recordings list query",
  "layer": "django",
  "parent": "session-replay",
  "markdown": "What it is, how data flows, what constraints matter. Code paths in backticks."
}
```

- `layer` must be one of the keys in `concepts.json`'s `layers` (frontend / django / ingestion / ci / agents today; add a layer only when a whole new system area appears).
- `parent` places it in the hierarchy; top-level concepts (`parent: null`) should be things you'd name in a sentence to any engineer. Prefer deepening an existing branch over adding top-level nodes.

## Reinforce before you write

Learnings work the way learning works: an idea is formed from experience, then **reinforced or not** by how often it is re-observed and whether it has predictive power.
Each learning carries an `observations` log, and its strength is the length of that log — strong learnings render with a thicker accent and sort first under their concept.

So the first question is never "what learning do I write?" — it is "which learning did this work just confirm?":

- **Re-observed**: the pattern happened again → append `{ "date": "YYYY-MM-DD", "kind": "observed", "note": "what happened", "task": <number> }` to that learning's `observations`, and add the task to `evidence_tasks`.
- **Predictive power**: the learning correctly predicted a problem, or you used it to avoid one → append the same with `"kind": "predicted"`. Predicted observations are the strongest signal a learning is true — say what it predicted.
- **Contradicted**: the world disagreed with the learning → don't silently delete it. Note the contradiction in its `markdown` and stop adding observations; a learning that stops being reinforced is visibly weak, which is itself information.

Only when no existing learning covers the idea do you write a new one (below), with its first observation.

## How to add a learning

1. Check `learnings.json` for an existing learning that covers the insight — reinforce it (above) rather than duplicating.
2. Append:

   ```json
   {
     "id": "short-kebab-slug",
     "title": "One-line statement of the learning",
     "markdown": "The why, with enough detail that a stranger gets it. Context as links: [#66590](https://github.com/PostHog/posthog/pull/66590).",
     "concepts": ["taxonomic-search"],
     "evidence_tasks": [12345],
     "observations": [{ "date": "2026-07-10", "kind": "observed", "note": "what happened", "task": 12345 }],
     "skills": [{ "name": "some-skill", "status": "proposed" }],
     "author": "your-name"
   }
   ```

   - `markdown` is the knowledge. PRs, issues, and docs are **context, not knowledge** — put them in the markdown as links, never as nodes.
   - `concepts` are the system concepts the learning is about; add the concept first if it doesn't exist yet (ingest fails on unknown ids, which is the guard against orphan learnings).
   - `skills`: the skill that encodes (status `existing`) or should encode (status `proposed`) the learning. Proposed entries are the shared backlog of skills worth writing.
   - `author`: your short name, consistent across entries — it powers the per-user filter. Match the local part of your email.

3. **Public-repo safety**: both files are committed to a public repository. No customer names, private operational scale, Slack quotes, or unreleased roadmap details. Qualitative descriptions and public PR numbers are fine.
4. Regenerate to verify it parses and links (unknown concept ids and layers fail loudly):

   ```bash
   python3 tools/dev-knowledge-graph/ingest.py
   ```

   Never commit `out/` — fetched conversation content is private and the directory is gitignored.

## When a learning should graduate

A `proposed` skill attached to a learning with **3+ evidence tasks** is ready to write for real — follow `writing-skills`, then flip its `status` to `existing` here.
If a learning describes a mechanically checkable convention, prefer the automation ladder (linter > lint-staged > skill > instructions) and say so in the body.
