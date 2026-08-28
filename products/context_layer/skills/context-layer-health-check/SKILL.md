---
name: context-layer-health-check
description: Review the semantic quality of a context wiki after the deterministic consolidation pass. Use this when you check a context-layer dream branch for problems the lint report cannot detect, such as contradictory active claims, unsupported conclusions, stale priorities, near-duplicate subjects, concepts without an owning page, and missing sources. Runs inside the mounted wiki repository, where the `scripts/lint` command is available.
---

# Context layer health check

You run inside the organization's mounted wiki repository.
PostHog scaffolds the `scripts/lint` command into that repository when the organization enables the context layer; it is not part of the PostHog application repository.

Read recent `wiki-miss:` lines from `git log --merges` and use them as the priority signal. Review for contradictory active claims, unsupported conclusions, repeated low-value activity, stale priorities the report cannot detect, near-duplicate subjects, concepts without an owning page, and sources worth backfilling.

Fix what evidence supports. Leave unresolved conflicts as `**Disagreement:**` markers and record remaining work in the run summary. Finish with `scripts/lint` and `scripts/lint --report`.

Do not edit `AGENTS.md`, `CLAUDE.md`, generated indexes, `scripts/`, or Space paths. The server owns wiki structure and tooling.
