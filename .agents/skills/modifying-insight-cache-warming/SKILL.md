---
name: modifying-insight-cache-warming
description: Guides changes to insight cache warming, dashboard access signals, warming priority, cache miss pressure, and related metrics. Use before editing posthog/caching/warming.py, dashboard access tracking, or insight cache warming scheduling.
---

# Modifying insight cache warming

Refresh this skill's implementation map before reviewing or changing code:

```bash
bash .agents/skills/modifying-insight-cache-warming/scripts/refresh-reference.sh
```

Then read [references/current-implementation.md](references/current-implementation.md). The refresh step is mandatory: it keeps this skill aligned with the current call sites, constants, metrics, migration state, and tests each time the skill is accessed.

## Preserve the access contract

- Keep `Dashboard.last_accessed_at` updated for every path that updates it today. It is a long-lived compatibility signal used outside cache warming.
- Record cache-warming access detail through `record_dashboard_access`; do not add direct writes to `most_recent_access` in views or serializers.
- Keep access methods distinct. Human, embedded, and API access have deliberately different priority and should not be merged into one timestamp.
- Use atomic database expressions for counters. A read-modify-save sequence loses increments under concurrent dashboard loads.
- Keep the JSON shape additive. Existing records and older application versions must remain readable during rolling deploys.

## Protect backpressure

- Treat the warming limit as a budget, not an eligibility threshold. Gather a wider stale pool, rank it, and schedule only the highest-priority candidates.
- Human access should dominate embedded access, and embedded access should dominate API access unless a recent cache miss supplies a bounded boost.
- Frequency can strengthen a source's priority but must not let high-volume API traffic outrank ordinary recent human use.
- Cache misses may increase priority only for a limited recency window. Never create a permanent priority boost from a historical miss.
- Keep a legacy fallback for dashboards that only have `last_accessed_at` while `most_recent_access` is being populated.
- Do not increase per-team concurrency. Warming tasks must remain chained and run on the analytics-limited queue.

## Keep behavior observable

- Add or update Prometheus metrics for access source, cache outcome, candidate outcome, miss boost, and selected priority.
- Keep metric labels bounded. Do not add dashboard IDs, insight IDs, team IDs, URLs, or user identifiers to new labels.
- Update the existing PostHog capture event when a new aggregate is needed for product analysis; do not emit one event per candidate.

## Validate changes

- Invoke `writing-tests` before changing tests.
- Test source ordering, cache-miss boosts, the warming budget, legacy fallback, and concurrent-safe access counter behavior when those areas change.
- Run `hogli test posthog/caching/test/test_warming.py products/dashboards/backend/test/test_access.py`.
- Run `ruff check` and `ruff format` on changed Python files.
- If the dashboard model changes, invoke `django-migrations`, inspect `sqlmigrate`, and keep `max_migration.txt` current.

After implementation, run the refresh script again and commit the regenerated reference with the code change.
