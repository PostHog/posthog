---
name: context-layer-consolidation
description: Keep a context wiki coherent by working the deterministic lint report queue. Use this on a context-layer dream branch to remove unsupported synthesis, expire stale priorities, mark superseded decisions, merge near-duplicate pages, and repair links. Runs inside the mounted wiki repository, where the `scripts/lint --report` command produces the queue.
---

# Context layer consolidation

You run inside the organization's mounted wiki repository.
PostHog scaffolds the `scripts/lint` command into that repository when the organization enables the context layer; it is not part of the PostHog application repository.

Start with `scripts/lint --report`. Work the queue on the current dream branch.

Only edit sourced Markdown content under `org/`, `areas/`, `decisions/`, and existing Space pages. Never edit repository instructions, generated indexes, or `scripts/`; report structural failures in the run summary for the server to repair.

- Remove unsupported synthesis.
- Remove expired priorities unless historically significant; mark those `status: historical`.
- Mark replaced decisions `superseded` and link their replacement.
- Merge near-duplicates and leave a wikilink from the old subject.
- Resolve disagreements only with evidence; leave the rest explicit.
- Repair or intentionally retain ghost links, add sources, and split oversized pages.
- Name every deletion in the commit message.

Keep this bounded and evidence-led. Run `scripts/lint` after editing.
