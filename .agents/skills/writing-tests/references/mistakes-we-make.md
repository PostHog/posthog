# Mistakes we actually make

Kent Beck's rule: _write tests for the sorts of mistakes you make._
This is the catalogue of mistakes PostHog actually ships and reverts — derived from merged `fix:` and `revert:` PRs and corroborated against recurring production incidents.

Use it as a sanity check, not a checklist.
When you're about to write a test, find the category your change touches and write the **cheapest** test at the level noted.
If your change doesn't map to any category here and isn't genuinely new behavior, be sceptical the test is worth keeping.

The headline: **most bugs that reach production are boundary and contract mistakes — null/empty/wrong-shape input, mis-classified errors, non-UTC time, cross-tenant leakage — and almost all are catchable at the cheapest rung of the pyramid.** The expensive rungs (ClickHouse, browser, async-teardown loops) are reserved for the genuine minority that needs them.

## Catchable cheaply — write these

### 1. Empty / null / wrong-shape input → 500

Code assumes a value is present (a row, a field, an aggregation result, a JSON body) and crashes or returns wrong data when it's absent or the wrong type, instead of degrading to a 400 or an empty result.
This is one of the two most common `fix:` clusters, and incident follow-ups repeatedly self-diagnose it as "we should have had a test for this."

- **Catch it at:** a pure unit test, or a Django `TestCase` hitting the endpoint with the bad value. No ClickHouse.
- [#62757](https://github.com/PostHog/posthog/pull/62757) — handle null metrics when serializing experiments — `NULL` metrics → `TypeError: NoneType is not iterable` on list/detail.
- [#11792](https://github.com/PostHog/posthog/pull/11792) — return 400 instead of 500 if event properties is not JSON — capture crashed on non-JSON properties.
- [#60996](https://github.com/PostHog/posthog/pull/60996) — handle `prompt=none` OIDC requests without 500 — a spec-compliant param hard-500'd silent login.
- [#61076](https://github.com/PostHog/posthog/pull/61076) — guard `wordPluralize` against null `group_type` — flag page crashed on `Cannot read properties of null`.

### 2. Retryable vs non-retryable error misclassification

A data-warehouse import source lets a _permanent_ failure (bad auth, deleted integration, expired password) surface as a _retryable_ error, so it retries forever and floods error tracking — or the inverse, a transient blip is wrongly made terminal and drops data.
The other most-common `fix:` cluster.

- **Catch it at:** a pure unit / Django `TestCase` asserting the source maps a given exception to the right (non-)retryable class. Cheap, no ClickHouse.
- [#63681](https://github.com/PostHog/posthog/pull/63681) — Snowflake: treat expired password as non-retryable.
- [#63677](https://github.com/PostHog/posthog/pull/63677) — Salesforce: treat deleted integration as non-retryable.
- [#63798](https://github.com/PostHog/posthog/pull/63798) — Postgres: keep transient SSL connection drops retryable (the inverse direction).

### 3. Tenant-isolation / scoping (IDOR)

A model or endpoint isn't scoped to the requesting team/org, or a fail-closed manager isn't used on a query path, exposing or crashing on cross-tenant data.

- **Catch it at:** a Django `TestCase` that creates two teams and asserts team B can't read team A's rows — PostHog's standard IDOR-coverage pattern.
- [#61901](https://github.com/PostHog/posthog/pull/61901) — add scoping checks across billing, dashboard collaborators, and CDP templates.
- [#62755](https://github.com/PostHog/posthog/pull/62755) — fix search tool crash for accounts kind — a fail-closed manager wasn't handled on the search path → `KeyError`.

### 4. Timezone / non-UTC correctness

Code assumes UTC; date bucketing, pagination cursors, and schedule resolution shift by a day or 500 for teams in other timezones.

- **Catch it at:** a pure unit / `TestCase` parameterized over a non-UTC team timezone, asserting the bucket boundary.
- [#61111](https://github.com/PostHog/posthog/pull/61111) — UTC-pin `time_bucket` truncation — non-UTC truncation broke keyset pagination cursors.
- [#57593](https://github.com/PostHog/posthog/pull/57593) — timezone-safe date parsing to prevent calendar-day shifts.

### 5. HogQL printer / type-coercion correctness

The HogQL → ClickHouse printer emits SQL that crashes ClickHouse with a cast error, or silently returns wrong results.

- **Catch it at:** a `TestCase` snapshot of the printed SQL (`test_printer.py` + `.ambr`) for shape bugs; escalate to `TransactionTestCase` + ClickHouse only when wrong _results_ need real execution.
- [#63220](https://github.com/PostHog/posthog/pull/63220) — make `toBool` null-safe — bare `toBool` hard-failed `Cannot parse boolean value` on UUID-shaped strings.
- [#58713](https://github.com/PostHog/posthog/pull/58713) — coerce funnel aggregation target before the empty check — a numeric-typed property hit `Cannot read floating point value while converting ''`.

### 6. Async / Temporal / workflow execution

Workflow code calls something the runtime rejects (unsupported logger kwargs, blocking calls), busts the activity retry/timeout budget, or hangs in fixture teardown.

- **Catch it at:** a unit / `TestCase` on the activity in isolation; a teardown hang needs an explicit timeout wrapper rather than a bigger timeout.
- [#60302](https://github.com/PostHog/posthog/pull/60302) — fix logger import — `temporalio.workflow.logger` rejected a `parallelism` kwarg and failed the workflow.
- [#62339](https://github.com/PostHog/posthog/pull/62339) — add a timeout wrapper to the `ateam` fixture teardown (a test-only guard for the recurring teardown hang).

## Catchable, but one rung up — write these sparingly

### 7. N+1 / unbounded / non-index-friendly query perf

A query wraps an indexed column in a function, hand-writes `JSONExtract`, or full-scans, timing out on large teams.

- **Catch it at:** a `TransactionTestCase` + ClickHouse/Postgres test asserting a query-count bound or the query shape. Index-friendliness is often best caught by reviewing the printed predicate, not a test.
- [#61864](https://github.com/PostHog/posthog/pull/61864) — resolve person via an index-friendly lookup — a `distinct_id` lookup timed out on large teams.
- [#62417](https://github.com/PostHog/posthog/pull/62417) — avoid slow AI query predicates — functions wrapped indexed columns and bypassed materialization.

### 8. Migration / schema drift

A migration references a table/column that doesn't exist yet (or is redundant), breaking startup or CI.

- **Catch it at:** migration replay in CI, plus a `TestCase` guarding the migrated state. Many of these only surface at apply time, so the CI replay is the real gate.
- [#59873](https://github.com/PostHog/posthog/pull/59873) — handle a missing `posthog_instancesetting` table during migrations.

### 9. Refactor-introduced regression (the revert-class)

A structural refactor ships, changes behavior, and gets reverted wholesale — usually because **no test pinned the old behavior** before the refactor.
This is the cautionary tail: the missing test is a _characterization_ test written _before_ the change.

- **Catch it at:** a characterization test capturing the pre-refactor behavior, at whatever level the surface lives. Write it first, then refactor.
- [#60485](https://github.com/PostHog/posthog/pull/60485) — undo a 10-PR taxonomic-filter extraction stack that made the picker worse.
- [#56785](https://github.com/PostHog/posthog/pull/56785) — revert a refactor of `Person` bulk-delete.
- [#59920](https://github.com/PostHog/posthog/pull/59920) — revert a fix that itself regressed non-boolean filter handling.

## Not test-shaped — don't fake a test for these

These dominate raw incident _volume_ but are prevented by monitoring, alerting, capacity, and CI config gates — **not** unit tests.
Don't write a unit test that pretends to cover them; it will be slow, flaky, and prove nothing.

- **Resource exhaustion under load** — OOM, connection-pool starvation, unbounded memory growth, event-loop blocking. The failure threshold is load-dependent; prevention is capacity and alerting. (A _known_ accidental O(n) or heavy per-call init can get a targeted perf regression test — the load itself cannot.)
- **Infrastructure / third-party failure** — node crashes, DNS/network changes, disk exhaustion, upstream-provider outages, broker throttling. Root cause is below the application; remediation is runbooks and monitoring.
- **Per-region config / deploy-ordering drift** — code deployed before its migration completes, or an environment-specific value wrong in one region. A subset is catchable by a config-validation check in CI; the ordering itself surfaces only in a real deploy.
