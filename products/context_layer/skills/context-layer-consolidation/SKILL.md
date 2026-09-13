---
name: context-layer-consolidation
description: Keep the context wiki coherent using the deterministic lint report queue
---

# Context layer consolidation

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
