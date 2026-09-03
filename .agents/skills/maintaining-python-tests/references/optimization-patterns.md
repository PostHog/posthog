# Test optimization patterns

Select a pattern only after measurement identifies the cost center.

## Reuse expensive infrastructure

Use this pattern when each case starts the same worker, consumer, client, container, or database helper.

Good shared state is expensive and immutable during a case:

- A Temporal worker on one task queue.
- A Kafka client or consumer factory.
- A database parser or schema registry.
- A container that hosts an external service.

Bad shared state contains case output:

- A tenant row reused by every case.
- One workflow ID or object-storage prefix.
- A consumer offset that the next test inherits.
- A mutable global patch.

A safe change has this shape:

1. Create the infrastructure once at module or class scope.
2. Give every case unique mutable identifiers.
3. Pass the shared object through an explicit fixture or helper parameter.
4. Keep teardown at the same scope as setup.
5. Run all modes and all cases together.
6. Run selected cases alone to prove that no previous case prepares them.

Measure setup, call, and full wall time. Fixture reuse often moves cost between phases.

## Preserve parameter cases

Do not remove values because they appear similar. Check which boundary each value exercises:

- Serializer validation.
- Normalization.
- Persistence.
- Database constraints.
- Post-save hooks.
- External client behavior.
- Query output.

Keep the full matrix when different values can fail at different boundaries. Optimize the shared work around the matrix.

Use parameterization to remove duplicated test code. Parameterization alone does not reduce execution cost.

## Replace incidental snapshots

A snapshot can be the main cost when it formats a large query, object graph, or rendered tree.

Remove a snapshot only when it describes implementation rather than behavior. Replace it with assertions that cover all meaningful output fields.

A safe replacement proves:

- The query or request still executes.
- Every mode still runs.
- The complete result shape remains correct.
- Important values remain exact.
- The test still fails for the regression it protects.

Do not replace a snapshot with a path-only or non-empty assertion. That weakens coverage.

## Reuse production work

A slow test can reveal repeated work in production. Optimize product code only after profiling proves the repeated work exists outside the test harness.

Examples include:

- Rebuilding the same database or schema object inside one operation.
- Parsing the same query several times.
- Fetching the same immutable configuration for each item in one request.

Keep API and integration cases after the production optimization. Strengthen persisted-state assertions when shared production work can cause cross-item contamination.

## Move a test to a cheaper level

Move a test to a cheaper level when its regression does not require its current boundary:

```text
pure function -> Django SimpleTestCase -> Django TestCase -> integration service
```

Keep one wiring guard at the higher level when the lower-level test cannot prove that the production entry point uses the tested component.

Examples:

- Put a DRF validation matrix in `SimpleTestCase`. Keep one endpoint 400 case.
- Test transformation logic as a pure function. Keep one pipeline round trip.

Do not mock the boundary that the test exists to prove.

## Use cheaper Django isolation

Prefer `SimpleTestCase` when no database access is needed.

Prefer `TestCase` when transaction rollback can isolate the case.

Use `TransactionTestCase` only when the regression requires committed transaction behavior. Database flushes make it expensive.

A change of the base class needs an isolation proof. Run the complete class more than once and in a different order when possible.

## Retire temporary migration tests

A dedicated data-migration test is temporary when all of these conditions hold:

- Every supported environment applied the migration.
- The rollback window closed.
- No supported upgrade begins from the old state.
- The behavior does not remain as a runnable command or reusable backfill.

Delete the expired test after explicit approval. Keep the migration file.

Keep tests for:

- Migration tooling and safety checks.
- Reusable backfill frameworks.
- Backfills that operators can still run.
- Production commands with active behavior.

Do not mark an expired test as skipped.

## Reduce database setup

Look for repeated creation of organizations, teams, users, schemas, and permissions.

Safe options include:

- Use a lighter base class.
- Create immutable parent rows once.
- Use factories that create only required fields.
- Move pure validation out of a database-backed endpoint matrix.

Do not share tenant rows when the code under test mutates tenant state. Unique tenant IDs are often the cheapest isolation boundary.

## Remove real waiting

A maintenance change must not add sleeps or retries.

Replace polling with one of these options:

- Await the workflow or task result.
- Flush the queue or consumer through a test helper.
- Freeze or advance the clock.
- Wait on an explicit condition with a bounded diagnostic error.

If the wait represents real external nondeterminism, use `/fixing-flaky-tests` before you change it.

## Improve ownership

An unowned slow test has two maintenance problems. Fix the path or ownership rule after you confirm the correct team.

Prefer the narrowest stable ownership path. Do not assign a broad directory to a team only to capture one file.

Verify the emitted `test.owner_team` value after the reporter change reaches CI. A local resolver result proves the rule. It does not prove the timing reporter emitted it.

## Common incorrect results

Reject these results:

- The test count fell because a filter stopped collecting cases.
- Call time fell because work moved to setup.
- One warm run is compared with one cold run.
- Local wall time is compared with CI call time.
- The average fell while p95 and the slowest-suite time increased.
- A snapshot was removed without equivalent result assertions.
- A worker was shared while cases reused mutable IDs.
- A broad before-and-after window is described as causal.

## When to stop

Stop work on a target when one of these conditions is true:

- The target no longer appears in the current high-cost ranking.
- The next change would weaken a meaningful boundary.
- The remaining time is required product behavior.
- Another shard now controls the critical path.
- The evidence does not identify a cost center.

Rebuild the ranking. Select the next measured target. Do not continue work on a test that no longer matters.
