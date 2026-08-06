# Mistakes we actually make

The bugs PostHog ships and reverts cluster into a small number of shapes.
This catalogs them — derived from merged `fix:` and `revert:` PRs, with each example checked at the diff level (does the PR actually add a regression test, and at what level?) and cross-referenced against recurring production incidents.

Use it to aim a test at a failure mode we really hit, not a hypothetical.
Find the shape your change touches and write the test at the level noted.
If your change maps to nothing here and isn't genuinely new behavior, be skeptical the test earns its place.

Two headlines:

- Most bugs that a test can cheaply prevent are **boundary and contract mistakes** — mis-classified errors, null/wrong-shape input, cross-tenant leakage, non-UTC time — caught at the bottom of the pyramid.
- Some real, costly failure modes are **not cheaply unit-testable** (query perf, migration ordering, async teardown, refactor regressions, resource exhaustion). Writing a unit test for those gives false confidence. Know which kind you have before you write anything.

## Bugs a cheap test catches — write these

### Mis-classified retryable vs non-retryable errors

A data-warehouse import source maps a _permanent_ failure (bad auth, deleted integration, expired password) to a _retryable_ error, so Temporal retries it forever and floods error tracking — or the inverse, a transient blip is made terminal and silently disables a customer's sync.
The most common `fix:` cluster, and the best-tested.

- **Catch it at:** a pure-unit test asserting the source maps a given exception string to the right (non-)retryable class. No Temporal, no ClickHouse. Assert _both_ directions.
- [#63677](https://github.com/PostHog/posthog/pull/63677) — Salesforce: treat deleted integration as non-retryable — a deleted OAuth integration raised `Integration not found`, a string the error map didn't match, so it retried forever; the test asserts that string is non-retryable _and_ that `Read timed out` stays retryable.
- [#63681](https://github.com/PostHog/posthog/pull/63681) — Snowflake: treat expired password as non-retryable — `Specified password has expired` wasn't in the non-retryable set.
- [#63798](https://github.com/PostHog/posthog/pull/63798) — Postgres: keep transient SSL drops retryable — `SSL connection has been closed unexpectedly` was wrongly non-retryable, so a mid-probe drop permanently disabled the sync (the inverse direction).

### Null / empty / wrong-shape input → crash

Code assumes a value is present or well-formed (a DB field, a JSON body, a group type) and crashes instead of degrading.
Common — and cheap to guard against relative to the cost of shipping it.

- **Catch it at:** the cheapest level that exercises the boundary — a pure-unit call with the bad value, or a Django `TestCase` hitting the endpoint. No ClickHouse.
- [#62757](https://github.com/PostHog/posthog/pull/62757) — handle null metrics when serializing experiments — a `NULL` `metrics` column reached `enumerate(None)`, so one bad row 500'd the whole experiments list; the test parameterizes null/empty combinations against the list and detail endpoints.
- [#11792](https://github.com/PostHog/posthog/pull/11792) — return 400 instead of 500 if event properties isn't JSON — subscripting non-dict `properties` raised `TypeError`; the fix converts it to a `ValueError` (→ 400), and the unit test calls the function directly and asserts that — a rung below even the endpoint.
- [#61076](https://github.com/PostHog/posthog/pull/61076) — guard `wordPluralize` against null `group_type` — a null group type crashed the flags page render; tested at the helper (Jest) and at the converter that produced the null (Python unit).

### Tenant-isolation / scoping (IDOR)

A query or endpoint isn't scoped to the requesting team/org, leaking reads or allowing writes across tenants.

- **Catch it at:** a Django `TestCase` that creates two orgs and asserts org B can't see or mutate org A's rows — PostHog's standard IDOR-coverage shape.
- [#61901](https://github.com/PostHog/posthog/pull/61901) — add scoping checks — the value is in the specific two-org tests, e.g. `test_plugin_unused_does_not_leak_other_orgs` (asserts the other org's plugin id is absent) and the dashboard-collaborator cross-project pair (asserts 404 and that the privilege row is unchanged). The PR itself bundles several unrelated fixes, so cite the test, not the bare PR.

### Timezone / non-UTC correctness

Code assumes UTC; date bucketing, pagination cursors, and chart labels shift by a day for teams in other zones — and CI's `TZ=UTC` hides it.

- **Catch it at:** usually the cheapest rung — a pure-unit test parameterized over non-UTC zones (plus a DST boundary). But when the truncation happens _inside ClickHouse_, the cheap test can't see it and you need real execution.
- [#57593](https://github.com/PostHog/posthog/pull/57593) — timezone-safe date parsing — frontend parsing read the system wall-clock and rolled the calendar day back east of UTC; a pure Jest test over UTC/LA/Tokyo/Berlin and a DST boundary catches it. The clean cheap exemplar.
- [#61111](https://github.com/PostHog/posthog/pull/61111) — UTC-pin `time_bucket` truncation — `toStartOfDay` truncated on the session-timezone grid while cursors printed UTC, emptying keyset page 2 under a non-UTC `session_timezone`. This one is _not_ cheap: the regression test inserts rows and runs the real SQL with `session_timezone=US/Pacific` (a ClickHouse-backed `TestCase`). Know which kind you have.

### HogQL printer / type coercion

The printer emits SQL that crashes ClickHouse with a cast error or returns wrong results.
These split into two test levels, and confusing them is a trap.

- **Catch a SQL-_shape_ change at:** a printed-SQL assertion or `.ambr` snapshot (`test_printer.py`), no execution. Fast — but it only proves the SQL changed, not that ClickHouse stopped erroring.
- **Catch a wrong-_result_ or hard error at:** a ClickHouse-backed `TestCase` that actually runs the query.
- [#63220](https://github.com/PostHog/posthog/pull/63220) — make `toBool` null-safe — bare `toBool` hard-failed on UUID-shaped strings, fixed to `accurateCastOrNull`. Caught with a printed-SQL string assert plus an `.ambr` snapshot; the snapshot proves the cast wrapper is present, nothing more.
- [#58713](https://github.com/PostHog/posthog/pull/58713) — coerce funnel aggregation target before the empty check — a numeric-typed property hit ClickHouse error code 72 (`Cannot read floating point value`); the `.ambr` diff alone (a `toString()` wrap) wouldn't prove the error is gone, so the real test executes `.calculate()` against ClickHouse.

## Real bugs where a checked-in unit test is the wrong tool

These failure modes are real and costly, but a cheap unit test either can't catch them or gives false confidence.
Reach for the right tool instead of writing a test that proves nothing.

- **Non-index-friendly / unbounded queries.**
  A function wraps an indexed column (`toString(uuid) IN ...`) or leaves `team_id` unbound, degrading to a scan that times out on large teams.
  The catch is an `assertNumQueries` / query-count bound or reviewing the printed predicate — not a happy-path test.
  Honest note: in our own history these shipped verified by hand, not by an automated bound — [#61864](https://github.com/PostHog/posthog/pull/61864) (unbound `team_id` → scan) pins only an RPC name through a mock, and [#62417](https://github.com/PostHog/posthog/pull/62417) (indexed column wrapped in `toString`) asserts input validation, not query shape. That gap is exactly what a query-bound test would close.

- **Migration / apply-time ordering.**
  Code reads a table before its migration creates it — [#59873](https://github.com/PostHog/posthog/pull/59873), a ClickHouse migration read `posthog_instancesetting` before it existed under parallel migration.
  No checked-in test guards this; the safety net is CI migration replay, which exercises the ordering. Don't write a unit test pretending to.

- **Async / Temporal teardown hangs.**
  An uncancellable `sync_to_async` gRPC call in fixture teardown hangs the whole job — [#62339](https://github.com/PostHog/posthog/pull/62339), fixed by removing the call and relying on DB CASCADE, not by a test.
  And beware the adjacent trap: a test that mocks the boundary it is supposed to verify catches nothing. [#60302](https://github.com/PostHog/posthog/pull/60302) fixed a real workflow-logger crash, yet its logger tests mock the logger — so they pass whether or not the crash is present and would miss a re-regression.

- **Refactor regressions that escape correctness tests.**
  A "behavior-preserving" refactor regresses on an axis the tests don't cover.
  The lesson isn't "add a characterization test" — it's "cover the behavior that actually changes."
  [#59920](https://github.com/PostHog/posthog/pull/59920) was reverted even though a data-executing correctness test existed — the regressing behavior was outside what that test asserted; [#56785](https://github.com/PostHog/posthog/pull/56785) had helper and API tests that passed cleanly through both the refactor and its revert.

## Not test-shaped at all

These dominate incident _volume_ but are prevented by monitoring, capacity, and alerting — never a unit test.

- **Resource exhaustion under load** — OOM, connection-pool starvation, event-loop blocking. Load-dependent; prevention is capacity and alerting. (A _known_ accidental O(n) can get a targeted perf test; the load itself cannot.)
- **Infrastructure / third-party failure** — node crashes, DNS or network changes, disk exhaustion, upstream-provider outages. Root cause sits below the application; remediation is runbooks and monitoring.
