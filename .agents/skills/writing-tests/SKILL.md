---
name: writing-tests
description: >
  Gates whether a new test should exist and keeps it cheap and honest, protecting CI from tests that guard nothing.
  Use before any change to what a pytest, Jest, or Playwright test asserts or sets up, down to one fixture or one assertion added to an existing block.
  Carries the value bar (every test catches a realistic regression no existing test catches; extend the nearest test with your case, not its mocks; drive input through the public interface and assert an outcome a caller observes; parameterize near-duplicates; break the guarded line and watch the test go red) and the cost bar (the lowest level of the cost ladder where the behavior exists; a real dependency only when the behavior uses it; stubs only at true boundaries; Django TestCase over TransactionTestCase; no sleeps; no time bombs from unpinned dates).
  For an existing flaky test use `/fixing-flaky-tests`; once this gate says a Playwright test is warranted, use `/playwright-test` for mechanics.
---

# Writing tests worth keeping

The handbook carries the rationale and the same rules for people: [Backend coding conventions › Testing](https://posthog.com/handbook/engineering/conventions/backend-coding#testing) (`docs/published/handbook/engineering/conventions/backend-coding.md`).
This skill is the gate an agent runs before it writes a test.
It holds the decision procedure and [a catalog of the bug shapes we actually ship](references/mistakes-we-make.md).
The gate covers added coverage, not only new test functions.
One fixture and one assertion added to an existing block go through the same questions, because that is the shape this skill prefers.

## The gate

Answer questions 1 and 2 in one sentence each before you write the test, and question 3 before you commit it.
A question you can't answer stops the test.

### 1. Does it earn its place?

> **What realistic regression does this test catch that no existing test already catches?**

Name the bug, the code path, and the input that would break it.
"Increases coverage", "good practice", and "the function exists" are not answers.
A good answer sounds like _"if someone makes `parse_filters` drop the `team_id` clause, this fails"_ or _"empty-cohort input used to 500; this locks in the 400."_

Aim each test at a failure mode we actually ship.
[references/mistakes-we-make.md](references/mistakes-we-make.md) catalogs those shapes, the test that catches each, and the failure modes no unit test should chase.
A test that maps to none of them is probably not worth keeping.

### 2. Where does it go?

Passing question 1 buys the coverage, not a new test function.
Find the test that covers the nearest behavior and answer:

> **Why can't this be a case in that test?**

When your case is a variation of that behavior, extend it with a `@parameterized` case in Python or a `test.each` row in Jest.
Write a standalone test only when you can name one of three reasons: the setup differs, the behavior belongs to a different unit, or no relevant test exists.
"It's cleaner as its own test" names none of them.

Extend to remove duplication.
A parameterized case is still its own invocation, so `setUp` and `beforeEach` run for it as they would for a standalone function, and extending saves no setup time.
Fold in variations of the same behavior, and give assertions about other behavior their own test.

Extending adds your case, not the neighbor's habits.
When the nearest test mocks internal helpers or asserts on mock calls, give your case real input through the public interface and assert an [outcome](#what-counts-as-an-outcome).
When that test's harness can't observe the outcome, the setup differs, so write a standalone test.

Search for the nearest test first; question 2 has no answer without it.

A new test file needs a team owner, because ownership routes its failures and flakes.
Put it next to the code it tests, inside `products/<name>/` when one product owns the behavior, so it inherits that owner.
Check with `hogli owners:who <path>`.
When no team owns the path, name the team responsible for the behavior it checks in the nearest `owners.yaml`, not the team of a helper it imports.
CI fails a pull request that leaves a test file with no team owner: a new file, a moved file, or a file that an `owners.yaml` edit left without a team.
The pre-push hook runs the same check and blocks the push.

### 3. Does it go red?

Break the line the test guards: drop the clause, flip the condition, or return early.
Run the test, and watch it fail for the reason you named in question 1.
Then restore the line.
For a bug fix, the pre-fix code is the broken line.

A test that stays green guards nothing.
Rewrite it to assert an outcome, or delete it.
This check catches tautologies and mock plumbing on every level, so run it on each test you add or change.

## Tests that guard nothing

Most low-value tests take one of these shapes.
Recognize them and skip them.

1. **Framework behavior.**
   Getters, setters, constants, dataclass field assignment, that Django saved a row, that DRF serialized a field, or that a library does what its docs say.
   That tests someone else's code.

2. **Change-detector tests.**
   A test that mirrors the implementation by asserting which private methods ran, in what order, with mocks wired to match the current code.
   It fails on every refactor and catches no real bug.
   Assert an [outcome](#what-counts-as-an-outcome) instead.
   See [Change-Detector Tests Considered Harmful](https://testing.googleblog.com/2015/01/testing-on-toilet-change-detector-tests.html) and [Prefer Testing Public APIs](https://testing.googleblog.com/2015/01/testing-on-toilet-prefer-testing-public.html).

3. **Redundant coverage.**
   Ten tests that run the same path with different data are one parameterized test.
   AI-generated suites bloat here first, turning a 30-second suite into 3 minutes with hundreds of near-identical cases.

4. **Coverage-chasing.**
   An uncovered line is information, not a defect.
   When the coverage report is the only reason to test a branch, the branch probably needs no test, or it is dead code to delete.

5. **Cross-language source scraping.**
   A test that reads or regex-parses another language's source, such as a Python test that `Path(...).read_text()`s a `.ts` file and matches `category: '...'`, or a TypeScript test that greps a `.py` file.
   It couples two trees through a string match that breaks on a rename, a reformat, a moved file, or a comment, and it proves nothing at runtime because the two sides never run together.
   When two sides must agree on a set of values, give them one source of truth, a generated artifact or a checked-in data file that both import, and assert against it.
   Otherwise let drift surface where the two sides meet: an API contract test, a rendered output, or a round trip.

When the answer is "skip it", extend an existing test or delete the code instead.
Both shrink the suite.

## What counts as an outcome

A test gives input through the unit's public interface and asserts an outcome, something a caller can observe:

- the return value of a pure function, through its own signature;
- the HTTP response, or the row the request stored;
- the `values` a kea logic exposes after its actions run;
- the message, email, or request that a boundary fake recorded, meaning the URL, body, and headers the receiving service reads.

The last one matters most for code whose job is to send.
For a destination or a webhook, the request that crossed the boundary is the delivery, so asserting on it tests the outcome.
A call to your own helper, its call count, or its arguments is not an outcome.

## If you write it, weight it down the cost ladder

Each level of the cost ladder is slower and flakier than the one below:

```text
pure function → kea logic → Django TestCase / Node service test → ClickHouse-backed test → Node serial lane / Playwright e2e
   cheapest                                                                                             most expensive
```

Aim for a ratio, not a cap: many tests at the bottom, very few at the top.
Add more coverage at the bottom.

Pick the lowest level where the behavior exists and its outcome is visible.
A lower level that sees only an internal call, or a mock standing in for the code under test, is not a cheaper test of the same behavior.
It tests something else.

Take a real dependency only when the behavior reads or writes it.
Logic that never touches Postgres, ClickHouse, or Redis belongs on a level without them.
Logic that does belongs on the real one, because a mock of it agrees with whatever the code assumes.

**When something is hard to test cheaply, that's a design signal: extract, don't escalate.**
When the only way to run your logic is a database, a request, and a render, the logic is tangled with its dependencies.
Pull it into a pure function or a kea logic and test it through that unit's own interface, its signature or its actions and values.
You get a faster test and better-factored code at once.
Mocking the tangled code's internal helpers also makes the test cheap, but then the test observes the mocks.
When the behavior can't be pulled out, because it lives in a query, a transaction, or the wiring, test it at the level where a caller observes it.

When you extract a decision this way, such as the dedupe, routing, or eligibility rule that [.agents/architecture.md](../../architecture.md) keeps pure, put the case matrix on the pure function and keep one database-backed test as a wiring guard.
Without that guard, a refactor that stops calling the decision passes every pure case.

Reach for ClickHouse, the Node serial lane, or a browser only when the regression lives there.

### Python (pytest / Django)

- **Use `TestCase`, not `TransactionTestCase`, unless you truly need it.**
  `TransactionTestCase` flushes the database between tests instead of rolling back a transaction, which is much slower and a common source of cross-test interference.
  The choice is about Postgres isolation, not about which datastore you touch: a ClickHouse-backed test is still a plain `TestCase`, because `ClickhouseTestMixin` sets ClickHouse up.
  The usual reasons for `TransactionTestCase` have cheaper answers:
  - For `transaction.on_commit` side effects, use `TestCase` with `self.captureOnCommitCallbacks(execute=True)`.
  - For a connection visible across a real separate thread (`thread_sensitive`), use `async_to_sync(...)`, not `asyncio.run(...)`.
    Use `TransactionTestCase` only when the regression needs committed transaction boundaries that `TestCase` hides.
- **A test class only takes a database it uses.**
  `BaseTest` and `APIBaseTest` inherit Django `TestCase`, so a class on either one needs a database: `setUpTestData` writes an organization, a project, a team, and a user, and every test method runs inside a transaction.
  A class of pure assertions pays all of that and reads no row.
  Put those cases on `django.test.SimpleTestCase`, which refuses database access and so proves they never needed one.
  The `posthog/test/repo_invariants/test_database_free_test_classes.py` check holds the frozen list of the classes already here and fails the pull request that adds another.
  When it trips, [references/database-free-test-classes.md](references/database-free-test-classes.md) covers what the failure means, the three ways to answer it, and how to regenerate the baseline.
- **Dedicated data migration tests are temporary.**
  Remove one after every supported environment has applied the migration, the rollback window has closed, and no supported upgrade relies on the old data state.
  Delete the expired test instead of marking it skipped.
  Keep the migration file, and keep tests for migration tooling, safety checks, reusable backfill systems, and backfills people can still run.
  Use `/django-migrations` for the migration safety workflow.
- **DRF input validation belongs in a `SimpleTestCase`, not an `APIBaseTest` round trip.**
  A test that posts a malformed body and asserts a 400 pays for `APIBaseTest` to build an organization, a team, and a user in Postgres, only to run validation that happens in memory.
  DRF field validators (`required`, type coercion, `choices`, `min`/`max`, regex) and `validate_<field>` methods run inside `Serializer(data=...).is_valid()` with no database and no request.
  Field-level validation runs in `to_internal_value`, before the object-level `validate()` that usually needs `self.context`, so an invalid-field case never reaches code that touches the database.
  Test the serializer directly and assert on `.errors`:

  ```python
  class TestTeamValidation(SimpleTestCase):  # no DB, not APIBaseTest
      def test_sample_rate_too_many_digits(self) -> None:
          s = TeamSerializer(data={"session_recording_sample_rate": "30001"}, partial=True)
          assert not s.is_valid()
          assert s.errors["session_recording_sample_rate"][0].code == "max_digits"
  ```

  When you move the case matrix down to the serializer, keep or add one database-backed endpoint test as a wiring guard, proving the viewset invokes this serializer and rejects a bad request with a 400.
  The serializer test proves the validation logic, not the wiring: a refactor that drops `serializer_class`, skips `is_valid()`, or stops passing `raise_exception=True` passes every `SimpleTestCase` and still ships a broken endpoint.
  For a query serializer built inline, such as `Serializer(data=request.query_params).is_valid(raise_exception=True)`, the wiring guard asserts that a bad query parameter returns a 400.
  `.errors` carries DRF's raw code (`invalid`, `max_digits`); `exceptions-hog` renders the `{"attr", "code", "detail", "type"}` HTTP envelope later and maps `invalid` to `invalid_input`.
  That rendering is framework behavior, so the wiring guard asserts the envelope once and the cases skip it.
  Validation that needs the database stays at the endpoint: uniqueness checks, `PrimaryKeyRelatedField` queryset lookups, related-object existence, permission and team scoping, and password-hash checks.

- **Parameterize** repeated assertions with the `parameterized` library rather than copying test bodies.
- **Use a `parameterized` case when the cases are known before the test runs, and `self.subTest` only when they are not**, such as one check per row a query returns.
  Our pytest configuration makes `self.subTest` fail fast so CI can retry the test.
  Use `self.subTest`, not the pytest `subtests` fixture, which leaves a failure in the junit file after a rerun passes.
- **No doc comments** in Python tests (house rule).
- **Drive your own helpers through the code that calls them.**
  A mock of an internal helper is how change-detector tests start.
  For Postgres, ClickHouse, and Redis, follow the real-dependency rule in the ladder section above.
- **Person, group, and cohort data:** use the helpers in `posthog/test/persons.py` (`create_person`, `create_group`, `create_group_type_mapping`, `add_cohort_members`, and others), never `Person.objects.create()` or similar ORM calls.
  See [`posthog/test/AGENTS.md`](../../../posthog/test/AGENTS.md) for the API and the reasons.
- **Whole-repo guards go in `posthog/test/repo_invariants/`.**
  A test whose input is the entire repo walks `apps.get_models()`, inspects `sys.modules` after a cold `django.setup()`, enumerates every route or signal receiver, or `rglob`s the tree against a baseline.
  Any file can break such a test, and diff-based test selection can't select it.
  That directory runs on every backend PR in the `repo-checks` CI job, products-only PRs and drafts included, without Postgres or ClickHouse, and the Core shards skip it.
  Tests with a bounded input stay next to the code they cover.

### Node (Jest, `nodejs/`)

- **Drive the consumer or service entry point the way production does.**
  Give it the real dependencies its behavior reads or writes, from the Postgres, Kafka, Redis, and ClickHouse that CI starts for every Node test job.
  Build the hub with `createHub` when the entry point takes a hub; otherwise construct the service with only those dependencies, such as a `PostgresRouter`.
- **Assert what a boundary recorded:** the request `mockFetch` received (`tests/helpers/mocks/request.mock.ts`), the message `mockProducerObserver` saw (`tests/helpers/mocks/producer.mock.ts`), the mail `MailDevAPI` reads from maildev, or the job row in Postgres.
  A spy on an executor or a service method is a change detector.
- **Keep case matrices out of the serial lane.**
  A `*.serial.test.ts` file runs with `--runInBand`, so every case in it adds straight to CI time.
  A test belongs there when it shares infrastructure it can't isolate (see [.agents/code-style.md](../../code-style.md)) or covers a flow across services that no lower level can see.
  Its case matrix still goes on a lower level.

### Frontend (Jest)

- One top-level `describe` block per file (house rule).
- When the behavior lives in a **kea logic**, test the logic, not a full component render: call its actions as a component would and assert on the `logic.values` a component reads.
  A `render()` and DOM-query test is for what only the DOM can show.
- `test.each` for variations rather than copied test bodies.
- **Avoid `*ByRole(..., { name: ... })` on components that render a large DOM**, such as calendars, the taxonomic filter, or whole scenes.
  Role queries walk every element, running `getComputedStyle`-based checks and accessible-name computation.
  That takes seconds per query in jsdom, multiplied by every `waitFor` or `findBy*` retry, and it has produced single tests with a 40-second p95 in CI.
  Prefer `getByText`, `getByTestId` or `data-attr` selectors, or `getByLabelText`, and scope with `within(<small container>)` when a role query is genuinely needed.
  The `jest-no-byrole-name-queries` semgrep rule flags this.
- **Snapshot a small, intentional value, or assert specific fields.**
  A snapshot of a large rendered tree or serialized blob is a change-detector test that bloats the repo and breaks on every unrelated change.

### Always: determinism and isolation

- **Control the state transition instead of racing it.** Choose the control that matches the behavior under test:
  - For elapsed-time behavior, enable fake timers before starting the work and advance exactly the duration the behavior requires.
  - For a final async result, use `wait_for` or `waitFor` on the observable result.
  - For an in-flight state, make the boundary fake or stub await a promise the test controls.
    Assert the pending state, release the promise, then assert the final state.
    A debounce, a `setTimeout`, a kea breakpoint, or a fast mock may already have settled by the next line.
    Test setup may shorten internal delays without changing production behavior.
- **No new `time.sleep` or non-zero `asyncio.sleep` calls in test code.**
  The `no-fixed-sleeps-in-tests` Semgrep rule blocks new calls in CI, including import aliases and calls with `noqa` comments.
  Calls already on the base branch stay allowed.
  When elapsed time is the behavior under test, explain why next to a specific `# nosemgrep: no-fixed-sleeps-in-tests` exemption.
  A fixed delay does not prove another operation finished.
  Replace the sleep with the control that matches the wait:
  - `time.time()` or `datetime.now()`: `time_machine.travel(..., tick=False)`, then `traveller.shift(...)`.
  - `time.monotonic()`: time-machine does not patch it. Patch the clock where the code reads it.
  - Another thread or process: `threading.Event`, a future, `thread.join()`, or the process's output stream. Use `posthog.test.waiting.wait_until` when the dependency only exposes a condition to poll.
  - A fake that must block until cancelled or timed out: `await asyncio.Event().wait()`.
  - Something that must not happen: `assert not event.wait(timeout=...)`.
  - Order between two writes: set each timestamp yourself.
- **An absolute date in a test is a time bomb until you pin the clock.**
  A fixture date keeps its meaning only while the real clock stays where you left it.
  When anything under test measures that date against `now` (an age, a window, a "recent" flag, an expiry), the assertion holds today and fails some weeks later, on every open branch at once.
  Pinning a date into application state does not pin the clock.
  A test that sets an "evaluated at" value to a fixed instant and leaves the wall clock real still fails once real time passes the window, because the code reads `now` again and the two stop agreeing.
  Pin the process clock to the instant the fixtures describe: `time_machine.travel(..., tick=False)` in Python, or `jest.useFakeTimers()` with `jest.setSystemTime()` in Jest, released by `jest.useRealTimers()` in a `finally`.
  Or write the fixture relative to `now` (`now - 2 days`), so the test states the distance.
  Pinning the clock covers only what reads it inside your process; the next rule covers the rest.
  Ask this of every absolute date in a test, not only of an explicit frozen clock: _what does this assert when today is a year past it?_
  If the answer is not "the same thing", fix it before you commit.
- **A frozen clock doesn't freeze the infrastructure.**
  `time_machine.travel` patches the clock inside your process.
  Everything outside it runs on the real clock: ClickHouse TTL, Postgres `now()` defaults, S3 lifecycle rules, another service's token-expiry check.
  Freezing to an absolute date and then writing rows that something judges by age builds a time bomb, green for weeks and then red for good once wall-clock time passes the retention window.
  It fails on every branch at once, so it looks as though whichever PR is in front of you caused it, and that misattribution costs more time than the fix.
  Most ClickHouse tables are already safe: they build their TTL through `ttl_period()` ([`posthog/clickhouse/kafka_engine.py`](../../../posthog/clickhouse/kafka_engine.py)), which returns `""` under `settings.TEST`, so tests get no TTL.
  A table that hardcodes its `TTL` clause opts out of that guard, and `ai_events` is one.
  Check rather than assume: `grep -rlE '^\s*TTL ' posthog/models/ posthog/clickhouse/ --include=*.py`.
  Make the row's lifetime independent of the ambient clock instead: pin the retention column on insert, the way `bulk_create_ai_events` writes `retention_days=10000`.
  Moving the frozen date forward only resets the timer.
- **Two writes in a row are not ordered in time.**
  Don't derive a cutoff from one write's recorded timestamp and expect the next write to land after it.
  Clocks are coarser than they look: library timestamps are milliseconds, and on Linux file mtimes come from the kernel's coarse clock, which lags the in-process clock by a scheduler tick.
  The library may also read a different clock than the one you sampled.
  delta-rs time travel resolves a datetime against the mtimes of the `_delta_log` commit files, not the `timestamp` that `DeltaTable.history()` reports.
  Such a test passes on macOS and fails every rerun on a fast Linux runner, so retries don't save it and it blames whichever PR is in the merge queue.
  Set the times yourself, minutes apart, with `os.utime` on the file or an explicit `created_at` on the row, and pick a cutoff between them.
  That also matches production, where the two events are seconds apart.
- **A test must not inherit a production timeout, latency budget, or retry deadline.**
  Code with a time budget reads it from config, and a test that calls that code without overriding it asserts how fast the CI runner is.
  Nothing at the call site shows this.
  `tester.invoke(...)` in a hog template test takes its 550 ms budget from `CDP_WATCHER_HOG_COST_TIMING_UPPER_MS`, and `executeLogTransformation(bytecode, record, globals, {})` takes 10 ms from `DEFAULT_LOG_TRANSFORMATION_TIMEOUT_MS`; both are defined two files away and neither is named in the test.
  Such a test passes with a wide margin on an idle laptop and fails on a loaded shard, where it reports the timeout as a wrong result.
  A hog transformation that runs out of budget returns `status: 'failed'`, so the assertion reads `Expected: "mutated" / Received: "failed"` and names neither the clock nor the budget.
  Pass the budget explicitly, large enough that it cannot bind.
  The test then asserts behavior, and the production number stays a production decision.
  Assert the whole result object rather than one field of it: `expect(outcome).toMatchObject({ status: 'mutated' })` prints the error on failure, and `expect(outcome.status).toEqual('mutated')` hides it.
- **Don't assert wall-clock duration.**
  `expect(elapsedMs).toBeLessThan(2000)` measures the runner, not the code, and on shared CI the runner is whatever else is running on it.
  It is usually dead as well: when the code under test has a shorter internal budget, that budget trips first, so the duration assertion can never be the one that fails.
  When a unit test must cover scale, assert the output at scale, every key present and nothing truncated, and leave timing to a benchmark.
- **No real network or live external services.**
  Use a fake that answers with the service's real response shape and refuses what the real service refuses.
  When the test needs one specific answer at a true boundary, such as a canned success, a timeout, a 500, or a dropped connection, a stub may return it.
  Either way, assert the outcome (the response, the stored row, the retry), not that the stub was called.
- **Tests pass in any order and in isolation.**
  A test sets up the state it reads instead of relying on what a previous test left behind.
- **A test must not inherit the CI matrix mode.**
  Backend CI runs one test under several modes, such as persons-on-events on and off, and a local run uses one of them.
  When the code under test branches on a mode, set the mode in the test, with one `@parameterized` case for each mode that matters.
- **A test you added that fails in CI blocks the merge, even when the job is green.**
  Trunk can quarantine a repeated failure, and a quarantined failure does not fail the job.
- **Every `@skip`, `xfail`, or `.skip` carries a one-line reason and a linked issue.**
  A permanently skipped test is dead weight: delete it or fix it.
- **Never commit `.only`** (`it.only`, `describe.only`).
  It runs only that test and skips every other test in the file, turning the suite green on a sliver.

## Before you open the PR

The PR template asks for this under "How did you test this code?", where a reviewer will see it.
One line per group of tests is enough:

> _"Added 3 cases to `test_cohort_query` covering empty, single, and oversized cohorts. Guards the 500 we just fixed, and fails when the empty-cohort branch is removed. No existing test exercised the empty path, so none could be extended."_

If you can't write that line, you've found a test that doesn't belong in the PR.

## Related skills

- **Fixing an existing flaky test:** use `/fixing-flaky-tests` to reproduce, root-cause, and validate.
  Use this skill too only when the fix adds or substantially changes coverage.
  That skill applies the gate above retroactively: a flaky test has already proven its cost, so when you can't name the regression it catches, deleting it is a valid outcome, not only stabilizing it.
- **Authoring a non-flaky Playwright test:** first use this skill to decide whether a browser test earns its cost, then use `/playwright-test` for the mechanics.
