---
name: context-layer-health-check
description: Semantic review of context wiki quality after deterministic consolidation
---

# Context layer health check

Read recent `wiki-miss:` lines from `git log --merges` and use them as the priority signal. Review for contradictory active claims, unsupported conclusions, repeated low-value activity, stale priorities the report cannot detect, near-duplicate subjects, concepts without an owning page, and sources worth backfilling.

Fix what evidence supports. Leave unresolved conflicts as `**Disagreement:**` markers and record remaining work in the run summary. Finish with `scripts/lint` and `scripts/lint --report`.

Do not edit `AGENTS.md`, `CLAUDE.md`, generated indexes, `scripts/`, or Space paths. The server owns wiki structure and tooling.
