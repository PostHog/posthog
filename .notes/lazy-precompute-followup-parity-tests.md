# Lazy-precompute follow-up: missing breakdown parity tests

**Trigger**: after the open lazy-precompute PRs (<https://github.com/PostHog/posthog/pulls/lricoy>) land on master.

## What's missing

`PARITY_BREAKDOWNS` in `products/web_analytics/backend/hogql_queries/test/test_web_stats_lazy_precompute.py` covers 7 of the 16 entries in `SUPPORTED_BREAKDOWNS`. The following nine breakdowns have no lazy-vs-raw parity test:

- `INITIAL_UTM_SOURCE`
- `INITIAL_UTM_CAMPAIGN`
- `INITIAL_UTM_MEDIUM`
- `INITIAL_UTM_TERM`
- `INITIAL_UTM_CONTENT`
- `INITIAL_UTM_SOURCE_MEDIUM_CAMPAIGN` — exercises the `concatWithSeparator` → `toJSONString` → `json.loads` roundtrip
- `CITY`
- `TIMEZONE` — exercises the `float(value)` decode branch (`_decode_breakdown_value`)
- `VIEWPORT` — parity (not just smoke); current tests skip it because raw query needs numeric viewport props the harness doesn't materialize

## What to do

1. Extend `_props()` in `test_web_stats_lazy_precompute.py` to seed UTM, timezone, and city event properties.
2. Add the nine breakdowns to `PARITY_BREAKDOWNS` (keep VIEWPORT separate with numeric `$viewport_width`/`$viewport_height`).
3. Run `pytest products/web_analytics/backend/hogql_queries/test/test_web_stats_lazy_precompute.py` and confirm parity.

## Why deferred

Raised by greptile on PR #59713. The PR's correctness is otherwise verified — added now would block the merge train without changing what ships. Cheaper to land after the stack flattens onto master so the fixture additions don't have to be rebased through every dependent branch.
