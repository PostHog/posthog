# Counting semantics

Type: grilling
Status: open
Blocked by: 01, 02

## Question

Define what paths v2 numbers _mean_, such that any displayed segment A→B maps to a funnel with identical results.

Decide, one by one:

- **Aggregation unit**: unique persons, per-session journeys (draft behavior: one person, three qualifying sessions → counts 3), or configurable (person/session/group — [#33488](https://github.com/PostHog/posthog/issues/33488)). Funnels count unique actors once.
- **Repeats**: does an actor who walks A→B in multiple sessions/journeys count once or per journey? Whatever the answer, name the funnel setting that reproduces it.
- **Window model**: gap-based session split (draft: `arraySplit` on inactivity) vs funnel conversion window (anchored at first step). If they differ, path→funnel equality breaks — pick one model or define the exact translation.
- **Ordering**: a path edge is _consecutive_ events (optionally deduping immediate repeats via `collapseEvents`) — closest to a strict-order funnel; a default (sequential) funnel would count more. Confirm the strict mapping and the collapse interplay.
- **Date-range anchoring**: funnels require step 1 in range; the draft requires each event in range. Align.

Output: a short semantics contract (what a node count, edge count, drop-off count mean; the funnel definition each maps to) recorded in the resolution and, if terms crystallize, `CONTEXT.md` via `/domain-modeling`.

Context: this is the root cause of the "paths numbers don't match other insights" complaints ([#37285](https://github.com/PostHog/posthog/issues/37285), [#32433](https://github.com/PostHog/posthog/issues/32433)).
