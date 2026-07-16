# Current insight cache warming implementation

This is the reviewed architecture reference. Run `scripts/refresh-reference.sh` for a fresh, read-only list of current call sites, constants, migration state, and focused tests.

## Access signals

- `Dashboard.last_accessed_at` remains the compatibility timestamp used by older application versions and code outside cache warming.
- `Dashboard.most_recent_access` stores additive records keyed by `human`, `embedded`, and `api`.
- Each access record can contain `timestamp`, `count`, `last_cache_miss_at`, and `cache_miss_count`.
- `record_dashboard_access` atomically increments counts and keeps both access timestamps monotonic when concurrent or delayed updates arrive.
- `record_dashboard_cache_outcome` records only misses in the JSON signal and keeps the miss timestamp monotonic.
- Insight serialization records miss pressure only for non-forced uncached dashboard requests. Multiple uncached tiles in one dashboard request coalesce to one miss write.

## Warming priority

- Candidate collection asks the query cache for a wider stale pool than the per-team warming budget.
- Standalone insights use recent `InsightViewed` activity and receive human priority.
- Dashboard candidates use source tiers that enforce human above embedded and embedded above API before miss pressure.
- Recency and frequency bonuses are bounded within a source tier, so high-volume API traffic cannot cross a tier by itself.
- Cache miss recency is scored independently from access recency. A sufficiently recent miss can explicitly cross source tiers, but the boost expires after its fixed window.
- A newer legacy `last_accessed_at` is considered even when `most_recent_access` is already populated, which preserves activity during rolling deploys.
- Dashboard insight pairs are queried in bounded chunks instead of constructing one OR expression for the full stale pool.
- Candidate counter increments are aggregated by bounded label tuple before being sent to Prometheus.

## Scheduling contract

- `MAX_WARMING_CANDIDATES_PER_TEAM` is a scheduling budget, not an eligibility threshold.
- Candidates are globally ranked after all query chunks have been evaluated, then only the highest-priority candidates are yielded.
- Per-team warming tasks remain a sequential Celery chain on the analytics-limited queue.
- Shared-only scheduling still requires an enabled sharing configuration.

## Compatibility and validation

- The JSON shape stays additive so older records and application versions remain readable.
- The migration introducing `most_recent_access` is `0015_dashboard_most_recent_access`.
- Focused tests live in `products/dashboards/backend/test/test_access.py` and `posthog/caching/test/test_warming.py`.
- Run the refresh script before and after changes, then run the focused tests and Python formatting checks listed in `SKILL.md`.
