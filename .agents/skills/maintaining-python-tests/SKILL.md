---
name: maintaining-python-tests
description: >
  Maintains existing pytest and Django test suites without weakening correctness. Use when asked to reduce Python test runtime or CI work, investigate slow pytest families, remove stale migration tests, consolidate repeated setup, improve Python test ownership, or measure whether a test optimization worked after merge. Ranks work by measured cost, applies the writing-tests value gate to existing coverage, preserves distinct behavior cases, validates isolation after shared-fixture changes, and separates testcase work from pytest-suite wall time. For an intermittent failure, use fixing-flaky-tests instead.
---

# Maintaining Python tests

Use this skill for an existing Python test suite. Use `/writing-tests` before adding or substantially changing coverage. Use `/fixing-flaky-tests` when intermittent failure is the main problem.

The goal is not a smaller test count. The goal is a suite that catches the same realistic regressions with less compute, less waiting, and less maintenance.

## Principles

1. **Measure before changing code.** Rank tests by total observed work, not by one slow local run.
2. **Preserve behavior coverage.** Keep cases that exercise different validation, persistence, integration, or output paths.
3. **Remove only expired or redundant coverage.** Get explicit approval before deleting a test.
4. **Share expensive infrastructure, not mutable test state.** Preserve isolation with unique IDs, schemas, tables, topics, or tenants.
5. **Measure after merge.** Local results prove the mechanism. Fresh master data proves the result in CI.
6. **Separate testcase work from suite wall time.** A change can reduce summed testcase time and not change the slowest pytest suite.

Read [measurement.md](references/measurement.md) before you query timing data or report an improvement.
Read [optimization-patterns.md](references/optimization-patterns.md) when you select a fix.

## Workflow

### 1. Define the result

Write down the user problem before choosing a test:

- Reduce total test compute.
- Reduce the slowest pytest suite.
- Remove expired maintenance burden.
- Restore test ownership.
- Reduce repeated external-service setup.

These results need different measurements. Do not claim faster CI when only summed test call time decreased.

### 2. Rank current work

Use recent PostHog test spans from `master` when available. Start with a complete window after the latest relevant merge.

Rank at least three views:

- **Individual tests:** execution count multiplied by duration.
- **Parameterized families:** all cases under one test function or fixture family.
- **Pytest suites or shards:** root-span wall time and the slowest suite per run attempt.

Use p50 to find steady cost. Use p95 to find contention or tail behavior. Use sampled observed hours to find repeated medium-cost tests. Use root-span testcase totals for complete pytest work.

Do not select a target from an old ranking after several fixes merge. Rebuild the ranking first.

Do not rank from `.test_durations`. It holds flat default values (0.01, 18.0, and 60.0) for tests that pytest-split could not time. These values are not measurements.

### 3. State why the test exists

Apply the `/writing-tests` gate to every target:

> What realistic regression does this test catch that no existing test already catches?

Then classify each case:

- **Distinct behavior:** keep it.
- **Same behavior with representative inputs:** parameterize it.
- **Framework or implementation detail:** replace it with an observable assertion, or propose to delete it.
- **Temporary migration coverage:** check whether every supported environment completed the migration.
- **Runnable backfill or reusable migration system:** keep active behavior coverage.

Do not infer redundancy from similar names. Read the setup, execution path, assertions, and production entry point.

### 4. Establish a baseline

Run the exact target with the same command that you will use after the change. Record:

- Test call time.
- Full command wall time.
- Setup and teardown time when available.
- Number of collected and executed cases.
- Whether the run was cold or warm.

Run the surrounding class or file when fixtures can change the result. A single test can hide repeated setup that only appears across the family.

Do not compare full pytest wall time with summed call time. They measure different work.

### 5. Find the cost center

Profile before rewriting. Attribute time to one of these groups:

- Test collection or environment boot.
- Fixture setup or teardown.
- Database creation, flush, or migration.
- Worker, consumer, broker, or container startup.
- Product code executed by the test.
- Snapshot serialization or formatting.
- Polling, retries, or real time.

Use a wall-clock profile for subprocesses and I/O. Use a CPU profile for Python or JavaScript work. A CPU profile can miss time spent in services or child processes.

### 6. Select the smallest safe fix

Prefer these options in order:

1. Remove expired coverage with explicit approval.
2. Replace incidental implementation assertions with stronger observable assertions.
3. Move the test to a cheaper level.
4. Reuse expensive immutable infrastructure across cases.
5. Reuse production objects only when the production path repeats unnecessary work.
6. Remove a distinct case only when another test proves the same regression through the same boundary.

Do not add timing assertions. CI timing is too noisy for a correctness test.

### 7. Preserve isolation

A shared fixture must not create an ordering dependency.

Before sharing setup, identify all state it owns:

- Tenant or team IDs.
- Database rows and transactions.
- ClickHouse tables.
- Kafka topics and consumer offsets.
- Temporal task queues and workflow IDs.
- Object-storage prefixes.
- Environment variables and global settings.
- Mocks and patched functions.

Give each case unique mutable state. Reset shared clients when their local cache or offset can affect the next case.

Run cases alone, together, and in a different order when the framework permits it. Run the family more than once when shared setup has process-level state.

### 8. Validate correctness and cost

Use this validation ladder:

1. Run the exact target.
2. Run the parameter family, class, or file.
3. Run related integration modes and pipeline versions.
4. Repeat the family when setup is shared.
5. Run lint, type checks, and repository preflight.

Keep exact result, response, persisted-state, or emitted-message assertions. Do not replace them with weaker row counts or truthiness checks to gain speed.

Use TDD when the change affects a helper or the contract of a test framework. Make the intended behavior fail first. For a pure runtime change, use a measured baseline instead of an unreliable timing test.

### 9. Report the local result accurately

Use this format:

```text
Target:       <test, family, or shard>
Regression:   <what behavior remains protected>
Cost center:  <measured source of time>
Change:       <smallest fix>
Before:       <metric, command, cases, cold/warm state>
After:        <same metric and conditions>
Correctness:  <focused and surrounding tests>
Isolation:    <how shared state stays separate>
Follow-up:    <post-merge query or none>
```

Do not report a percentage from two different measurement types.

### 10. Verify after merge

Wait for fresh `master` runs that contain the merge commit. Compare equivalent windows and cohorts.

Check all relevant outcomes:

- Exact test p50 and p95.
- Family sampled time per workflow attempt.
- Slowest affected suite per workflow attempt.
- Complete JUnit testcase time per workflow attempt.
- Slowest pytest-suite wall time.
- Failure rate and test count.
- Unowned test-span share when ownership changed.

If summed testcase time falls but suite wall time does not change, report both facts. Select the next target from the current slowest shard.

If the expected metric does not change, do not declare success from local data. Check whether the cost moved into fixture setup, teardown, or another test.

## Deletion rules

Get explicit user approval before you delete tests. Then confirm all of these conditions:

- You can name the behavior that the test covered.
- Another named test covers it, or the production behavior no longer exists.
- No supported upgrade, rollback, or runnable command needs the old state.
- You keep migration source files and active backfill coverage.
- The surrounding suite passes without hidden ordering dependencies.

Delete expired tests. Do not leave them skipped. A skip keeps unused code and can still add collection or service cost.

## Boundaries

- Do not remove cases to improve a count.
- Do not use sleeps, retries, or larger timeouts as performance fixes.
- Do not mock the behavior that the test exists to prove.
- Do not convert integration coverage to a unit test unless an integration wiring guard remains.
- Do not optimize production code only for a test. Confirm that the repeated work exists in production.
- Do not edit CI workflows as part of a test-runtime fix.
- Do not use PR runs as the post-merge result. Use fresh `master` runs.
- Do not claim causality from a broad before-and-after window when unrelated changes also merged.

## Related skills

- `/writing-tests`: decide whether new or changed coverage earns its cost.
- `/fixing-flaky-tests`: reproduce and fix intermittent failures.
- `/debugging-ci-failures`: classify a failing CI run before changing a test.
- `/django-migrations`: change or remove migration-related code safely.
- `/establishing-code-ownership`: add or correct ownership rules.
- `/querying-posthog-data`: verify the trace schema and HogQL before reading CI timing data.
