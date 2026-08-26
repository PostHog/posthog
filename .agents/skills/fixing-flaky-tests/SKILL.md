---
name: fixing-flaky-tests
description: >
  Guides an agent through reproducing, root-causing, fixing, and validating flaky tests in the PostHog monorepo.
  Use when a test fails intermittently in CI but passes on rerun or locally, when `hogli ci:insights` or the debugging-ci-failures skill classifies a failure as a flaky test, when given a GitHub Actions URL for a flaky job, when asked to check Trunk Flaky Tests for a test, PR, or master, or when asked to deflake, stabilize, or fix a flaky Jest, pytest, or Playwright test.
  Core discipline: reproduce locally before changing anything, fix the root cause (never mask it with sleeps, retries, or bigger timeouts), and prove the fix with an N-run validation loop sized to the observed failure rate.
  Stabilizing is not the only valid outcome — the skill also gates whether the test should exist, so deleting a test that catches nothing real, or re-leveling one that flakes because of the level it runs at, are first-class endings.
---

# Fixing flaky tests

Three non-negotiables, in order:

1. **Reproduce before you fix.** A fix for a failure you never observed is a guess.
   Only fall back to analytical fixes when the escalation ladder below is exhausted.
2. **Fix the root cause.** Sleeps, raised timeouts, retries, and weakened assertions hide flakes; they do not fix them.
3. **Validate with an N-run loop.** One green run proves nothing about an intermittent failure.
   Size N to the observed failure rate.

Stabilizing the test is not the only valid ending.
Once you know why it flakes, step 5 asks whether it should exist.
A test that catches nothing real is worth deleting, and one that flakes because of the level it runs at is worth moving down a rung.

Before any of these: **measure, don't assume.** Flaky-vs-deterministic, and the rate, are facts to establish from verifiable GitHub run data (step 1) — never inherited from a Slack alert, a teammate's guess, or a `ci:insights` label.

For triaging a red CI run (finding and classifying the failure), use the `debugging-ci-failures` skill first — this skill takes over once the failure is classified as a flaky test.
For writing new Playwright tests that aren't flaky, use the `playwright-test` skill.
`investigating-ci-failures` (green/red boundary) and `diagnosing-ci-and-merge-bottlenecks` (the `engineering-analytics-flaky-tests` tool's caveats) are product skills under `products/engineering_analytics/skills/`, not invocable here: read their `SKILL.md` at that path.

## 1. Measure the failure rate — from GitHub, not from a digest

The GitHub Actions API (or GitHub MCP) is the source of truth. `hogli ci:insights` is a digest, not an oracle — it can mislabel flaky-vs-deterministic, it lags the API until GitHub's webhook settles, and it cannot give you a rate at all: it reports absolute counts, because CI emits failures but omits ordinary passing runs, so there is no denominator. Use it to _validate_ a hypothesis or pull historical context, never as the first move or the classification authority.

Establish the timeline yourself from raw run data:

```bash
# Pass/fail history for the workflow on the branch under suspicion (master shown):
gh run list --repo PostHog/posthog --workflow=ci-backend.yml --branch master \
  --status completed --limit 60 --json conclusion,headSha,createdAt,databaseId
```

The run-level conclusion is not enough — a red run may be failing on a _different_ job/test. Confirm it is the **same test** each time by reading the failing shard's log; and for green runs, confirm the test actually **ran and passed** in that shard (it may have been sharded elsewhere, not fixed):

```bash
gh api repos/PostHog/posthog/actions/jobs/{job_id}/logs \
  | grep -E "<exact::test::id>|short test summary"
```

Read the timeline before you classify:

- **Interleaved pass/fail on adjacent commits** — the same unchanged test verified passing in some runs, failing in others → genuinely **flaky**; continue here.
- **A long unbroken failure streak** (say 30+ consecutive) is statistically incompatible with a flake — at any per-run rate below ~95%, `p^30 ≈ 0`. That is a **deterministic regression**: go to `debugging-ci-failures` and find the introducing commit (step 4).
- **Both at once** is common: a latent flake whose rate jumped to ~100%. Find the transition (last green → first red); that boundary, not the digest's one-line verdict, is what tells you what tipped it. `products/engineering_analytics/skills/investigating-ci-failures/` has the boundary query if the failure reached master.

If a failure is reported as (or you suspect it is) **consistent**, don't serialize — measure the rate and attempt a repro **in parallel**.

Record the **measured** rate (failures / total runs, from the run data). You need it to size the validation loop in step 7.

Then confirm it is not already handled:

```bash
git log --oneline -10 -- <test_file_path>          # recently fixed already?
hogli ci:insights search "<test name or error>"    # cross-run history — corroborate against the run data, do not trust blindly
```

`search` reports two surfaces; read each for what it actually claims:

- **broken tests** (recent failure fingerprints, last 2 days). A `potentially_resolved` state means that job's latest default-branch run is green again — weak evidence a fix landed, not proof. Confirm _against the run data_ that it covers this failure before reporting instead of re-fixing.
- **test health** (ranked by blast radius; the same spans the `engineering-analytics-flaky-tests` MCP tool reads). `confirmed_flake` is the only classification backed by proof: one commit both failed and passed the test in the same matrix job, via a re-run attempt going green or an in-job retry. A pass in a different matrix leg is not recovery. `suspected_regression` means no recovery was recorded — absence of proof, not proof of a regression, so treat it as real until your own run data says otherwise.

### Corroborate with Trunk Flaky Tests

CI uploads test results to [Trunk Flaky Tests](https://app.trunk.io/posthog-inc/flaky-tests?repo=PostHog/posthog), which tracks per-test failure history across `master` and PR runs.
On a PR, the `trunk-io` bot's "Trunk Test Analytics" comment links that PR's slice (`https://app.trunk.io/posthog-inc/flaky-tests/pr/<number>?repo=PostHog/posthog`).

The `trunk` MCP server in `.mcp.json` queries it (tools are marked experimental by Trunk):

- `search-test` (`repoName: "PostHog/posthog"`, `testNameSearch: "<test name, no filepath>"`) → the test case ID.
- `fix-flaky-test` (`repoName`, `testCaseId`) → failure history, first-seen commit, git blame, and Trunk's root-cause investigation; `createNewInvestigation: true` triggers a fresh analysis (takes up to a minute).

Authenticate once via `/mcp` → `trunk` (browser OAuth); headless environments instead add an `Authorization: Bearer` header with a `TRUNK_API_TOKEN` org token to the server entry.

Like `ci:insights`, this is corroboration and history, not the classification authority — flaky-vs-deterministic and the rate still come from the run data above.

## 2. Extract the failure from CI

```bash
gh run view <run-id> --log-failed
# If the job was re-run and the latest attempt passed, the flaky failure
# lives in a previous attempt:
gh api "repos/PostHog/posthog/actions/runs/{run_id}/attempts/1/jobs"
gh api "repos/PostHog/posthog/actions/jobs/{job_id}/logs"
```

Capture before moving on:

- Exact test ID (file path + test name) and the failing assertion or error.
- Surrounding warnings — `[MSW] Unhandled`, async leak warnings, teardown errors — these are often the actual cause, printed before the symptom.
- Which other tests ran in the same worker/shard before it (ordering suspects).

## 3. Reproduce locally — before touching anything

Escalate through these conditions until the failure appears.
Stop at the first level that reproduces it; that level is your validation environment for step 7.

1. **Single run**: `hogli test <path>::<test>` — confirms the test runs at all.
2. **Repetition loop** (default N=20): catches probabilistic flakes.
3. **CI-like conditions**: CI runs Jest sharded with low worker counts on contended runners — read the current flags from `frontend/package.json`'s `test` script and `.github/workflows/ci-frontend.yml` before running.
   Example (with the flags as of this writing), running the test alongside its shard neighbors:

   ```bash
   pnpm --filter=@posthog/frontend jest <test_file> <neighbor_file> --maxWorkers=2 --forceExit
   ```

   For pytest, run the whole file or class rather than the single test, so module-level fixtures and ordering match CI.

4. **Ordering**: run suspected polluter tests before the victim; reverse the order within the file.
   Flakes that vanish in isolation are ordering bugs.
5. **Contention**: re-run the loop while something CPU-heavy runs in another shell (e.g. a parallel full-file jest run).
   Timeout-class flakes often only show here.

The loop harness — judge by exit code, not by grepping output:

```bash
N=20; PASS=0; FAIL=0
for i in $(seq 1 $N); do
  if <test command> >/tmp/flake-run.log 2>&1; then
    PASS=$((PASS+1))
  else
    FAIL=$((FAIL+1)); cp /tmp/flake-run.log /tmp/flake-fail-$i.log; echo "run $i: FAIL"
  fi
done
echo "$PASS passed, $FAIL failed out of $N"
```

Two cost notes for the loop:

- While reproducing, `break` after the first failure — one captured failure log is enough.
  Complete all N runs only when measuring the failure rate or validating in step 7.
- The `pnpm --filter=@posthog/frontend jest` script runs `pnpm build:products` before every invocation.
  Inside a loop, build once, then iterate with `pnpm --filter=@posthog/frontend exec jest ...`, which skips the rebuild.

**If nothing reproduces after the full ladder**, the flake is CI-environment-specific.
Proceed with a fix grounded in the CI evidence and root-cause analysis, and say so explicitly in the report — the validation in step 7 is then analytical, not empirical.

## 4. Root-cause the flake

Match the symptom to a cause class; never patch the symptom.

| Symptom                                                | Likely cause class                                           |
| ------------------------------------------------------ | ------------------------------------------------------------ |
| Timeout waiting for promise/listener/element           | Unawaited async work, missing mock, hidden pending request   |
| Passes alone, fails with neighbors (or vice versa)     | Shared state: module cache, DB rows, global config, ordering |
| Fails near midnight/UTC boundaries, or on slow runners | Real clock usage — missing `freeze_time` / fake timers       |
| Assertion on list order or generated IDs               | Nondeterministic ordering/IDs asserted as deterministic      |
| Query can't see just-written data                      | Eventual consistency (ClickHouse), missing flush/commit      |
| Only fails under `--maxWorkers=2` / contention         | Race condition surfaced by scheduling, too-tight timeout     |

### When the cause isn't obvious, bisect

If the symptom table doesn't point at a clear cause and the test file itself is unchanged (`git log -- <test_file>` is stale), the trigger is elsewhere — a neighbor test, a dependency bump, or a product change. Find _when_ it started instead of guessing:

- **Bisect the CI run history first** (cheap, no local builds): from the step-1 timeline, take the last-green → first-red boundary and diff the commits in that window (`git log <good>..<bad>`). That short list often names the culprit outright.
- **`git bisect` the code** when you can reproduce locally and the failure is (near-)deterministic:

  ```bash
  git bisect start <bad-sha> <good-sha>
  git bisect run bash -c '<repro command>'   # exit 0 = good, non-zero = bad
  ```

  Caveat: for an intermittent flake, a _lucky pass_ at a step sends `git bisect` down the wrong path. Trust code-bisect only when the failure is deterministic; otherwise run the repro N times per step (fail if **any** iteration fails), or just use the CI run-history boundary.

PostHog-specific patterns:

### Frontend (Jest + kea)

- **Missing MSW mocks**: kea logics with `afterMount` loaders fire API calls through the `connect()` chain — a logic three levels deep can trigger an unmocked fetch.
  Unhandled requests currently resolve with a benign empty paginated 200, so the symptom is a loader succeeding with empty or wrong data, not a network error.
  The `[MSW] Unhandled GET ...` warning in the log names the missing mock — add the `useMocks` entry.
  The unhandled-request behavior has changed before (it used to hang); if symptoms don't match, read `frontend/src/mocks/jest.ts` for what unmocked requests do today.
- **`toFinishAllListeners()` timeouts**: waits for ALL kea listener promises across ALL mounted logics (3s default — `LISTENER_FINISH_WAIT_TIMEOUT` in `kea-test-utils`).
  Any connected logic with a pending loader blocks it.
  Fix the pending work; do not raise the timeout.
- **Mock URL mismatch**: `mocksToHandlers` strips trailing slashes, but query params, `@current`-style segments, and `:param` patterns must match the real request URL.
  Compare against the `[MSW] Unhandled` line.
- **Per-test handler reset**: `frontend/src/mocks/jest.ts` registers a global `afterEach(() => mswServer.resetHandlers())`.
  Each `it.each` case is a separate test, so runtime mocks must be (re-)registered in `beforeEach`.
- **Leaked mounts**: logics mounted in `beforeEach` and never unmounted leak async work into later tests.

### Backend (pytest)

- **DB state leakage**: shared rows across tests without isolation — check fixture scope and whether the test needs `@pytest.mark.django_db(transaction=True)`.
- **Real time**: use `freeze_time`; never assert on `now()`-derived values.
- **ClickHouse eventual consistency**: a query may not see just-inserted data — flush explicitly in the test setup rather than sleeping.

## 5. Decide the outcome — fixing is one of three

Once you know _why_ it flakes, ask whether the test should exist at all, before you spend effort stabilizing it.
A flaky test is the one case where cost is already proven and value is not: it has demonstrably cost reruns, wall-clock, and attention.
So apply `/writing-tests`' gate retroactively, with more force than you would to a new test:

> **What realistic regression does this test catch that no existing test already catches?**

Three outcomes are valid. Pick deliberately; don't default to the first.

| Outcome         | When                                                                           | Next   |
| --------------- | ------------------------------------------------------------------------------ | ------ |
| **Fix it**      | Guards a real regression at roughly the right cost.                            | step 6 |
| **Re-level it** | Worth guarding, but the flake is inherent to the level it runs at.             | below  |
| **Delete it**   | You cannot name the regression it catches, or another test already catches it. | below  |

### Delete it

Recurring shapes that fail the gate:

- **Tautological smoke test.** Asserts a precondition many sibling tests in the same file already need to run at all — that the chart rendered, that the list is non-empty.
  Every later test is a stronger version of it.
- **Duplicated coverage.** A thinner second test of a path an existing test already exercises.
  Fold it in as a parameterized case, or drop it.
- **Third-party assertion.** Flaky because it exercises a vendor's eventual consistency, scheduler, or API rather than our logic.
  That is the vendor's test to write, and mock-based siblings usually already cover our side.
- **Permanently gated.** Skipped everywhere but CI (missing credentials, opt-in marker), so nobody develops against it and only CI pays for it.

Deletion is irreversible, so it carries a **higher** bar than a fix:

- **Get explicit user approval**, the same gate quarantine carries.
  Propose the deletion and hand back; don't take it yourself.
- Account for the coverage: name what still catches this at file:line, or say plainly what is lost and why that's acceptable.
  "Probably covered elsewhere" is not an answer — go read the sibling test.
- Never delete to turn a red build green under time pressure.
  That is quarantine with extra steps, and it is how real regressions ship.

Then skip to step 8: there is nothing to loop.

### Re-level it

Move the test down the cost ladder in `/writing-tests` rather than hardening it in place.
A round trip through a real broker, browser, or vendor API to prove logic a direct call could prove is testing the transport, and the transport is where the nondeterminism lives.
Re-leveling removes the flake by construction, so prefer it over an increasingly elaborate wait.

The replacement is a new test: run `/writing-tests`' gate on it, and validate it at its new level rather than against the old repro conditions, which no longer exist.

## 6. Fix the root cause — never mask it

| Tempting masking move                                              | Do instead                                                                                                                   |
| ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------- |
| `sleep(2)` / `setTimeout` before asserting                         | Await the specific condition (`waitFor`, `expectLogic`, explicit flush)                                                      |
| Raise the test/listener timeout                                    | Find what is hanging; the timeout is the messenger                                                                           |
| Add retries (`pytest-rerunfailures` `--reruns`, `jest.retryTimes`) | Reserve for genuinely nondeterministic external infra, with a comment and a linked issue — never for product code under test |
| Skip / quarantine the test                                         | Only with explicit user approval, with a linked issue                                                                        |
| Loosen the assertion                                               | Make the data deterministic (sort, freeze, seed), keep the assertion strict                                                  |
| Harden a test that shouldn't exist                                 | Go back to step 5 — deleting or re-leveling it is the cheaper fix                                                            |

Keep the fix minimal and inside the test or its fixtures when possible.
If the race is in product code, the flake found a real bug — fix the product code and say so in the report.

## 7. Validate with an N-run loop

Run the step-3 harness on the fixed code **under the same conditions that reproduced the failure** (same neighbors, worker count, contention).

Size N from the observed pre-fix failure rate: if it failed about 1 in k runs, you need roughly **N ≥ 3k** consecutive passes for ~95% confidence the flake is gone — `(1 - 1/k)^(3k) ≈ 5%`.
So use **N = max(3k, 20)**.
Without a usable rate estimate, run 50 and note the reduced confidence in the report.
If the flake was never reproducible locally, run N = 20 as a regression check and label the validation as analytical.

Any failure in the loop → back to step 4; the root cause was wrong or incomplete.
Finish with one normal run of the surrounding file/suite to confirm the fix didn't break sibling tests.

Re-leveled instead? The old repro conditions no longer apply.
Loop the replacement at its own level, and confirm the flake is gone because the old test is gone, not because it got faster.

Deleted instead? Nothing to loop.
Run the surrounding file/suite once to confirm nothing depended on it, and carry the coverage argument into the report.

## 8. Report

```text
Test:            <file path>::<test name>
Observed in CI:  <measured rate from run data, e.g. 8/45 runs over 3h (gh run list); ci:insights state corroborates>
Local repro:     <command + conditions, e.g. 3/20 failures with neighbor X, maxWorkers=2 | not reproducible locally>
Root cause:      <one or two sentences>
Outcome:         fixed | re-leveled (<from> → <to>) | deleted
Change:          <what changed and why it removes the cause; for a deletion, what still covers the behavior (file:line) and what coverage is genuinely lost>
Validation:      <N>/<N> passes under repro conditions | <N>/<N> at the new level | analytical only (CI-specific) | n/a, deleted
Follow-ups:      <product bug found, related tests with the same pattern, or none>
```

## Boundaries

- Do not rerun CI jobs, push, or post to GitHub to "test" the fix — validate locally.
- Do not edit `.github/workflows/` as part of a flake fix.
- Do not accept/update snapshots to make a flake pass.
- If the same root-cause pattern clearly affects sibling tests, fix them in the same change only when mechanical; otherwise list them as follow-ups.
- Do not delete a test without explicit user approval, plus either a named replacement for the coverage or a plain statement of what is lost.
  Deletion is a valid outcome, never a shortcut to green.
