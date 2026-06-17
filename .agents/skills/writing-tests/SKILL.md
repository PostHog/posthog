---
name: writing-tests
description: >
  Gates whether a new test should exist and forces it to be efficient, protecting CI from low-value test bloat.
  Use before adding or substantially changing any pytest, Jest, or Playwright test — whenever an agent or engineer is about to write tests for a new feature, bugfix, or PR.
  Front-loads the value bar (every test must catch a realistic regression no existing test already catches; test behavior through the public interface, not implementation details; collapse near-duplicates into parameterized cases) and the efficiency bar (deterministic, isolated, fast; pick the cheapest test level; Django TestCase over TransactionTestCase; no sleeps, no real network).
  Includes a "don't write it" decision tree. For fixing an existing flaky test use `/fixing-flaky-tests`; for authoring a non-flaky Playwright test use `/playwright-test`.
---

# Writing tests worth keeping

A test suite is a shared, permanent liability.
Every test you add runs on every PR forever — it costs CI minutes, it can flake and block unrelated work, and someone else maintains it through every future refactor.
PostHog merges thousands of PRs a month; a test that doesn't pull its weight is a tax everyone pays and no one chose.

So the bar is two independent axes, not a single "more vs fewer" dial:

- **Value** — does this catch a realistic mistake _we actually make_? Maximize this.
- **Cost** — how far down the test pyramid does it sit? Minimize this.

You should have _thousands_ of fast, dependency-free tests; what you ration is the slow ones (a database, ClickHouse, a browser).
"Don't write low-value tests" never means "write fewer tests" — it means kill the ones that catch nothing (below) and push the rest as far down the pyramid as they go.
This skill is the gate. Run it before writing tests.

## The gate: one question

Before writing any test, answer in one sentence:

> **What realistic regression does this test catch that no existing test already catches?**

If you can't answer it concretely — name the bug, the code path, the input that would break — **do not write the test.**
"Increases coverage", "good practice", and "the function exists" are not answers.

A good answer sounds like: _"if someone makes `parse_filters` drop the `team_id` clause, this fails"_ or _"empty-cohort input used to 500; this locks in the 400."_
That is a test worth keeping.

Aim each test at a failure mode we actually hit, not a hypothetical.
The bugs PostHog ships and reverts cluster into a handful of shapes — cataloged with the test that catches each, and the failure modes no unit test should, in [references/mistakes-we-make.md](references/mistakes-we-make.md).
If your test doesn't map to one of them, be skeptical it's worth keeping.

## Don't write it — the four no's

Most low-value tests fall into one of these. Recognize and skip them.

1. **Trivial / framework behavior.**
   Don't test getters, setters, constants, dataclass field assignment, that Django saved a row, that DRF serialized a field, or that a library does what its docs say.
   You're testing someone else's code, not yours.

2. **Change-detector tests.**
   A test that just mirrors the implementation — asserting which private methods were called, in what order, with mocks wired to match the current code — fails on every refactor and catches no real bug.
   Test _observable behavior through the public interface_ (return value, persisted state, emitted event, HTTP response), not the choreography that produces it.
   See [Change-Detector Tests Considered Harmful](https://testing.googleblog.com/2015/01/testing-on-toilet-change-detector-tests.html) and [Prefer Testing Public APIs](https://testing.googleblog.com/2015/01/testing-on-toilet-prefer-testing-public.html).

3. **Redundant coverage.**
   Ten tests that exercise the same path with different data are one parameterized test.
   If a new test is a variation of an existing one, it's a `@parameterized` case (Python) or a `test.each` row (Jest) — **not** a new test function.
   AI-generated suites bloat here first: hundreds of near-identical cases turning a 30s suite into 3 minutes.

4. **Coverage-chasing.**
   Don't add tests to hit a number; an uncovered line is information, not a defect.
   If the only reason to test a branch is the coverage report, the branch probably doesn't need a test — or the code is dead and should be deleted instead.

When the answer is "don't write it," the right move is often to **extend an existing test** (add a parameterized case) or **delete code** rather than test it.
Both shrink the suite's surface.

## If you write it — weight it down the pyramid

A test that earns its place still has to be cheap.
Cost is a ladder; each rung is roughly an order of magnitude slower and flakier than the one below:

```text
pure function / unit  →  kea logic test  →  Django TestCase  →  ClickHouse-backed test  →  Playwright e2e
        cheapest                                                                                most expensive
```

The goal is a **ratio**, not a cap: many tests at the bottom, very few at the top.
A thousand pure unit tests are cheaper and more reliable than ten that boot Django, which are cheaper than one Playwright run.
Want more coverage? Add it at the bottom.

**When something is hard to test cheaply, that's a design signal — extract, don't escalate.**
If the only way to exercise your logic is to stand up a database, a request, and a render, the logic is tangled with its dependencies.
Pull it into a pure function or a kea logic and test _that_ directly: you get a faster test and better-factored code at once.
Escalating to the next rung is the last resort, not the default.

- If logic is in (or can be moved to) a pure function, test the function — don't stand up a DB, a request, or a render.
- Frontend: test the **kea logic** (`logic.actions` / `logic.values`), not a full component render, whenever the behavior lives in the logic.
  A `render()` + DOM-query test is for things only the DOM can show.
- Reach for ClickHouse or a browser only when the regression genuinely lives there — not because it was the first way the test came to mind.

### Python (pytest / Django)

- **`TestCase`, not `TransactionTestCase`, unless you truly need it.**
  `TransactionTestCase` flushes the DB between tests instead of rolling back a transaction — dramatically slower, and a common source of cross-test interference.
  It's a Postgres-isolation choice, orthogonal to which datastore you touch: a ClickHouse-backed test is still a plain `TestCase` (`ClickhouseTestMixin` sets ClickHouse up), so reaching ClickHouse is not a reason to switch.
  The cases that genuinely need it:
  - testing `transaction.on_commit` side effects → use `TestCase` + `self.captureOnCommitCallbacks(execute=True)`.
  - needing a connection visible across a real separate thread (`thread_sensitive`) → `async_to_sync(...)`, not `asyncio.run(...)`.
- **Parameterize** repeated assertions with the `parameterized` library — don't copy-paste test bodies.
- **No doc comments** in Python tests (house rule).
- Mock only **true boundaries** — network, external APIs, the clock, queues.
  Don't mock your own internal helpers (that's how change-detector tests are born).

### Frontend (Jest)

- One top-level `describe` block per file (house rule).
- Prefer logic tests over component renders (see the ladder above).
- `test.each` for variations rather than copied test bodies.
- **No huge snapshots.**
  A snapshot over a large rendered tree or serialized blob is a change-detector test that bloats the repo and breaks on every unrelated change.
  Snapshot a small, intentional value, or assert specific fields instead.

### Always — determinism and isolation

- **No `time.sleep` / arbitrary waits.**
  Use fake timers, `wait_for` / `waitFor` on a real condition, or `freeze_time`.
  A sleep is a flake waiting to happen, and it slows every run.
- **No real network / live external services.** Mock the boundary.
- **No cross-test ordering.**
  Tests must pass in any order and in isolation; don't rely on state a previous test left behind.
- **No `@skip` / `xfail` / `.skip`** without a one-line reason and a linked issue.
  A permanently-skipped test is dead weight — delete it or fix it.
- **Never commit `.only`** (`it.only` / `describe.only`).
  It doesn't skip one test, it skips every _other_ test in the file — turning the suite green on a sliver.

## Before you open the PR

State the justification where a reviewer will see it (PR description / agent-context).
One line per group of tests is enough:

> _"Added 3 cases to `test_cohort_query` covering empty / single / oversized cohorts — guards the 500 we just fixed; couldn't extend an existing test because none exercised the empty path."_

If you can't write that line, you've found a test that shouldn't be in the PR.

## When this skill does not apply

- **Fixing an existing flaky test** → use `/fixing-flaky-tests` (reproduce, root-cause, validate).
- **Authoring a non-flaky Playwright test** → use `/playwright-test` for the mechanics.
- This skill is about _whether and how cheaply_ to add a test; those are about a specific kind of test you've already decided to write or fix.
