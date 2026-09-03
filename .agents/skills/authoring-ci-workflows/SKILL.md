---
name: authoring-ci-workflows
description: >
  Use when adding or editing a GitHub Actions workflow, composite action, or reusable workflow under `.github/` — new CI jobs, triggers, matrices, checkout/clone tuning, action pinning, GitHub App token auth, concurrency groups, `timeout-minutes`, `paths` filters, caching, or runner choice.
  Covers PostHog's workflow-authoring conventions and the reasons behind them: the 500-runs/10s dispatch cap, shallow vs full clone, per-SHA push concurrency, dedicated App-token rate-limit buckets, and fork-safe secrets on a public repo.
  Points to the linters (`bin/hogli lint:workflows`, actionlint) that enforce the mechanical rules, and to the narrower skills for production deploys, secrets, and Depot runners.
  Not for debugging red CI (use debugging-ci-failures) or wiring a new secret end to end (use managing-github-actions-secrets).
---

# Authoring CI workflows

Before you propose a change to CI, check [things already tried](../../../docs/internal/ci-things-already-tried.md) for the idea. It records what was measured, and why some good-sounding changes were reverted or rejected.

Conventions for `.github/workflows/**` and `.github/actions/**`.
The linters own the mechanical rules (below); this skill is the **judgment calls** they can't enforce.

## Before you write

- Copy from a canonical file rather than from memory.
  `ci-paths-filter.yml` is the smallest complete example (triggers, concurrency, timeout, app token, Depot runner);
  `ci-backend.yml` is the reference for the heavy patterns (bounded-depth checkout, per-SHA concurrency, draft/ready, sharding).
- Related skills — reach for these instead of duplicating them here:
  - `/gating-production-deploys` — any job that pushes a prod image or dispatches a Charts deploy.
  - `/managing-github-actions-secrets` — creating the GitHub App / secret a workflow reads.
  - `/depot-github-runners` — Depot runner labels and sizing.
  - `/debugging-ci-failures` — CI is red and you need to know why.

## What the linters already enforce

Run `bin/hogli lint:workflows` and `actionlint` before pushing — they gate CI, and they (not this list) are the source of truth for what's enforced.
Today that's: `timeout-minutes` on every job, the canonical PR concurrency block, a repo-wide budget for unscoped PR event dispatches, `dorny/paths-filter` negation safety, justification for full-depth checkouts, cache-write gating, semgrep service coverage, required-check gate hygiene, and generic GHA correctness (bad `secrets.*` / `needs:` refs, deprecated `::set-output`, unknown runner labels).
Third-party action digests are bumped by Renovate.

## The dispatch budget (500 runs / 10s / repo)

GitHub caps _workflow-run dispatch_ at 500 runs per 10s per repo; overflow fails as `startup_failure` and takes unrelated runs in the same window down with it (a stack restack pushing many branches is the usual trigger).
**Minimize runs dispatched, not just work done** — draft status doesn't help, runs dispatch before skip logic applies.

- A reusable-workflow call counts as **one** run.
  Small always-fire PR workflows should be jobs under a single `workflow_call` parent, not their own dispatches (see `pr-updated.yml` / `pr-opened.yml` folded behind their parent — [fold pr housekeeping into one dispatch](https://github.com/PostHog/posthog/pull/68964)).
  Event-type scoping moves to job-level `if:` guards:

  ```yaml
  jobs:
    turbo:
      if: contains(fromJSON('["opened", "synchronize", "reopened"]'), github.event.action)
      uses: ./.github/workflows/ci-turbo.yml
  ```

- Prefer a trigger-level `paths:` filter over dispatch-then-skip: a run that only starts to no-op still spends a dispatch ([gate container workflows on trigger paths](https://github.com/PostHog/posthog/pull/68975)).

  ```yaml
  on:
    pull_request:
      paths:
        - '.github/workflows/ci-x.yml'
        - 'path/to/product/**'
    workflow_dispatch:
  ```

- **Judgment call — trigger `paths:` vs a runtime `dorny/paths-filter` job.**
  Use trigger `paths:` for a workflow that is _skippable as a whole_.
  Never put a trigger `paths:` on a workflow whose check is **required** by branch protection: a required check that doesn't dispatch on a PR leaves it stuck "waiting for status" and unmergeable.
  Keep those firing on every PR and gate internally with a `changes` job (also the right call when several jobs branch on different path sets).
  Heavy matrices (`ci-backend`, `ci-nodejs`) do exactly this — deliberate.
- Delete dead dispatchers outright.
  A disabled-but-still-triggered workflow keeps dispatching no-op runs against the cap — remove the trigger, don't just disable it.

## Concurrency

Every PR-triggered workflow gets the canonical block:

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.head_ref || github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
```

- Cancel superseded **PR** runs; never cancel across **master** pushes.
  `WF002` rejects a bare `cancel-in-progress: true` on any push-triggered workflow.
  Where latest-wins is genuinely right (a cache warmer), say so with `# hogli-lint: allow-master-cancel -- <reason>`.
- Use `github.ref` as the fallback, never `github.run_id` — `run_id` is unique per run, so it silently gives every push its own group and dedup is lost.
- Publish-on-push workflows must not let two master pushes race `:latest` / a deploy dispatch.
  Key the push arm per-SHA (see `ci-backend.yml`):

  ```yaml
  group: ${{ github.workflow }}-${{ github.event_name == 'push' && github.sha || github.head_ref || github.ref }}
  ```

## Required-check gates

The "gate" is the collate job that emits the required status check by reading `needs.*.result`.
By convention its display name ends in `Pass` (`Django Tests Pass`, `Visual regression tests pass`), but `WF007` also finds gates structurally when a step reads `needs.<dep>.result`, because the convention is not universally followed.
A job that inspects results without gating anything opts out with `# hogli-lint: not-a-required-gate — <reason>` above the job key.
Gates and the workers they inspect share the **same** condition:

| Job     | Condition                 | Why                                                                                                           |
| ------- | ------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Gate    | `if: ${{ !cancelled() }}` | It emits an explicit verdict on every completed run, and a superseded run records `cancelled`, not `failure`. |
| Workers | `if: !cancelled()`        | So a superseded run actually stops instead of holding the concurrency slot.                                   |

The gate condition must contain `!cancelled()`, with optional `${{ }}` wrapping.
`always()` is rejected: it is identical to `!cancelled()` on any run that is not cancelled, but on a superseded run it runs the gate after the cancel and reports `failure`, which inflates every CI failure-rate metric with runs a developer merely pushed over.

**Extra predicates may only be OR-ed on, never AND-ed.**
This is a correctness rule, not a style one.
A conjunction gives the gate a second way to be false, and a job skipped by its own condition records `skipped`, which branch protection reads as a pass.
Both conclusions occur in the same cancelled run: in [run 33496887370](https://github.com/PostHog/posthog/actions/runs/33496887370) `Calculate running time` recorded `cancelled` while `Backend coverage report` recorded `skipped`, because an AND-ed predicate of its own was already false.
A disjunction cannot be false while `!cancelled()` is true, so cancellation stays the gate's one false predicate and the conclusion stays `cancelled`.

Cancellation still fails closed.
A gate on `!cancelled()` that never starts records conclusion `cancelled`, never `skipped`.
Measured on a superseded run ([evidence](https://github.com/PostHog/posthog/actions/runs/33513529762)): the gate recorded `cancelled` with zero steps, while the `always()` control ran after the cancel and recorded `failure`.
GitHub's [status checks reference](https://docs.github.com/en/pull-requests/reference/status-checks) lists `success`/`neutral`/`skipped` as passing and never places `cancelled` among them, and a commit whose only checks are cancelled rolls up to `FAILURE` ([evidence](https://github.com/PostHog/posthog/actions/runs/33513732017)).
That is inference rather than a documented guarantee, which is the reason for the next rule.

**A workflow that cancels its own run must OR that signal onto its gate.**
`ci-backend` cancels itself when repo checks or OpenAPI types fail deterministically, to stop paying for runners on a failure a retry cannot fix.
Under a bare `!cancelled()` those real failures would report `cancelled` too, which both hides them from the failure-rate metric and rests merge safety on the inference above.
OR-ing the deterministic-failure output back on keeps the honest verdict, because the disjunct is true, so the gate dispatches despite the cancel:

```yaml
if: >
  !cancelled()
  || needs.repo-checks.outputs.deterministic_failure == 'true'
  || needs.check-openapi-types.outputs.deterministic_failure == 'true'
```

Measured on a self-cancelled run ([evidence](https://github.com/PostHog/posthog/actions/runs/33513529687)): the bare `!cancelled()` gate recorded `cancelled`, the OR-ed gate ran and recorded `failure`.
Only superseded runs then report `cancelled`, and every real failure keeps a `failure` conclusion.

Four rules for the gate body:

1. **Allowlist every dependency, never denylist.** Assert `success`/`skipped` and fail everything else.
   A dependency tested only against `== 'failure'` lets `cancelled` through, and one bad dependency is enough — a gate that clears four correctly and one with a bare `failure` test is still wrong.
   The trap is the `changes` detector: clearing it with `== 'failure'` and then reading `needs.changes.outputs.*` reports green on cancellation, because those outputs are empty and the gate takes its "nothing to test" exit.
2. **`needs` every job that produces coverage.**
   If a job's failure would only cascade into a downstream job being _skipped_, the gate reads that as a pass and you get a green check with zero tests run.
   Name the upstream job explicitly.
3. **Legitimate skips must still pass.** A frontend-only PR skips backend jobs by design.
4. **Every dependency's result must reach a fail-closed allowlist guard.**
   One inline `if` per dependency is the clearest form, but a shared shell helper or an `env:` block is equally fine: `WF007` traces each result through assignments, `${!var}` indirection, and helper argument positions within that step.
   The guard must compare with `!=`, join multiple allowed values with `&&`, and unconditionally `exit 1` when entered.
   Comparisons in another step, comments, logs, or branches that do not exit nonzero prove nothing and are rejected.
   A result whose guard `WF007` cannot follow is reported rather than assumed safe, so an unusual routing may need the checks moved inline.

`WF007` enforces 1, 4, and the `!cancelled()` condition, and it takes the dependency list from `needs:` as well as the step body, so a job you wired into `needs:` and then forgot to test is reported rather than silently trusted.
The half of rule 2 it cannot check is whether you named the right jobs in `needs:` to begin with: "reporting job" and "coverage job" look identical to a linter, so that one is on you and the reviewer.

## Checkout / clone — sparse first, then shallow

This repo is 45k tracked files and 4.6 GiB of packed objects, so **what you materialize costs more than how much history you fetch**.
Measured checkout-step durations, from the GitHub API on real runs:

| Pattern                                         | depot-ubuntu-24.04 | GitHub-hosted ubuntu |
| ----------------------------------------------- | ------------------ | -------------------- |
| `sparse-checkout` of a few paths, cone mode off | 0–7s               | 0–7s                 |
| plain checkout (depth 1)                        | 11–13s             | 22–44s               |
| `fetch-depth: 1000` + `filter: blob:none`       | 53–59s             | —                    |

- **Biggest lever: check out only the paths the job reads.**
  Sparse-checkout is not just for single files — a job that runs a local composite action, reads a JSON config, or lints one directory should name those paths and nothing else.

  ```yaml
  - uses: actions/checkout@<sha> # v6
    with:
      sparse-checkout: |
        .github/actions/paths-filter
        .github/clickhouse-versions.json
      sparse-checkout-cone-mode: false
  ```

- **Always set `sparse-checkout-cone-mode: false`.**
  Cone mode additionally materializes every file in the repo root — here 70 files and 21.5 MB, `.test_durations` alone 18.5 MB — which is most of what you were trying to avoid.
  Cone mode also only takes whole directories, so it drags in all of `bin/` when you wanted one script.

- **`filter: blob:none` is counterproductive if the job then materializes the tree.**
  It removes blobs from the fetch, but `git checkout` immediately lazy-fetches every blob in HEAD in a second round trip, which is slower than having fetched them in the pack.
  That lazy fetch also intermittently fails its per-blob credential lookup with `could not read Username for github.com` (#59779, blocked a merge until retried).
  Pair `blob:none` with `sparse-checkout` so the lazy fetch is a handful of blobs, or drop it and take the plain depth-1 checkout.

- **Default:** plain `actions/checkout` (depth 1). Add nothing.

- **Diffing against the PR base:** you need real history, so bound the depth, filter blobs, **and** sparse-checkout the files the job reads:

  ```yaml
  - uses: actions/checkout@<sha> # v6
    with:
      fetch-depth: 1000
      filter: blob:none
      sparse-checkout: .github/actions/paths-filter
      sparse-checkout-cone-mode: false
  - name: Fetch PR base for affected diff
    if: github.event_name == 'pull_request'
    env:
      BASE_REF: ${{ github.event.pull_request.base.ref }}
    run: git fetch --no-tags --depth=1000 --filter=blob:none origin "$BASE_REF:refs/remotes/origin/$BASE_REF"
  ```

  A sparse working tree does not affect `git merge-base`, `git diff <a>...<b>`, `git log --name-status`, `git ls-tree`, `git ls-files`, or `git show <rev>:<path>` — those read the object database or the index.
  Only commands that compare against the worktree (`git diff HEAD`, `git status`) see the skip-worktree entries.
  One caveat when `blob:none` is also set: `git show <rev>:<path>` still needs that blob, and a sparse checkout never downloaded it, so the read becomes a lazy fetch that can fail.
  Name any file a step reads that way in the sparse set — `ci-dagster.yml` does this for `docker-compose.base.yml`, whose contents feed a cache key.

- **`changes` / paths-filter gating jobs:** on `pull_request` the vendored `.github/actions/paths-filter` diffs via the GitHub API and never touches the tree.
  The only reason to check out is that a local action must exist on disk, so sparse-checkout `.github/actions/paths-filter` plus any file the job's own steps read.
  **Never pass `base: HEAD` to paths-filter from a sparse job** — that routes it to `git diff HEAD`, which a sparse worktree makes return nothing, so every downstream job silently skips green.

- **Foot-gun:** `git fetch --deepen=N` with **no refspec** falls back to the wildcard `refs/heads/*` and pulls _every branch_.
  Always pass an explicit, `--no-tags`, `--filter=blob:none` refspec scoped to the base ref.
  (Bumping `actions/checkout`'s own `fetch-depth` is safe — it uses a scoped `refs/pull/N/merge` refspec.)
- The linter rejects `fetch-depth: 0` unless you add `filter: blob:none`, use `sparse-checkout`, or justify it with `# hogli-lint: allow-full-depth-checkout -- <reason>`.
  Genuinely full-history jobs: repo mirroring (`foss-sync.yml`), tag/submodule version math (`release-cli.yml`, `desktop-tag.yml`).
  Most base-diff jobs should use bounded `1000 + blob:none` **plus** a sparse set.

## Pinning and tool versions

- **Pin every third-party action to a full 40-char commit SHA** with a `# vX.Y.Z` comment.
  A moved tag can ship malicious code; pinning is also reproducible and skips a per-run GitHub-API version lookup.
  The only sanctioned exception is a debug-only action.
  In-repo composites use a local path with no ref (`uses: ./.github/actions/pnpm-install`).
- **Node version comes from `.nvmrc`** — `node-version-file: .nvmrc`, never a hardcoded `node-version:`.
  Sparse-checkout `.nvmrc` if the job has no checkout.
- **Pin `setup-uv`'s `version:`** — an unpinned `setup-uv` calls the GitHub API on every job and burns the rate limit.

## Network fetches

Downloads from outside the runner need retries, or a transient reset becomes a red check with no findings ([actionlint died on `curl: (35)`](https://github.com/PostHog/posthog/actions/runs/32022348027/job/95364480249)).

```bash
curl -fsSL --retry 5 --retry-all-errors --retry-max-time 60 --connect-timeout 10 -o "$out" "$url"
```

- `--retry-all-errors` is the part that catches a reset; plain `--retry` covers only timeouts and 408/429/5xx, and `--retry-connrefused` adds `ECONNREFUSED`, not `ECONNRESET`.
- Drop it on GitHub API calls: with `-f` it also retries 403 and 404, spending five more requests on an already-empty token bucket.
- No `--retry-delay` (it replaces exponential backoff with a fixed wait). Keep `-f`, or an error page lands in your output file at exit 0.
- Don't retry anything non-idempotent (webhook posts, telemetry), or where a shell loop or readiness wait already retries.

## Tokens — dedicated App tokens for high-volume calls

`GITHUB_TOKEN` shares one ~15k req/hr bucket across every job of every run in the repo; it goes hot at merge peaks and change-detection jobs fail before real work starts.
A dedicated GitHub App installation is its own bucket — rate-limit headroom plus blast-radius isolation.

```yaml
- uses: actions/create-github-app-token@<sha> # v3.1.1
  id: app-token
  # forks can't read org secrets — fall back to github.token
  if: github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository
  with:
    client-id: ${{ vars.GH_APP_POSTHOG_PATHS_FILTER_APP_ID }}
    private-key: ${{ secrets.GH_APP_POSTHOG_PATHS_FILTER_PRIVATE_KEY }}

# a later step consumes the token (falling back to github.token on forks):
- uses: some-action@<sha>
  with:
    token: ${{ steps.app-token.outputs.token || github.token }}
```

- **Right-size, don't over-isolate.** One heavy consumer (change detection on a hot matrix) deserves its own app; a long tail of light workflows can share `GITHUB_TOKEN`.
  Convention: `GH_APP_<PURPOSE>_APP_ID` (an org **variable** — app IDs are not sensitive, and org secret slots are capped at 100) + `GH_APP_<PURPOSE>_PRIVATE_KEY` (an org secret).
- Cross-repo tokens set explicit `owner:` + `repositories:` (least privilege).
- Creating the app + secret is out of scope here — use `/managing-github-actions-secrets`.

## Forks and untrusted PRs (public repo)

Fork `pull_request` runs (and Dependabot) get a read-only `GITHUB_TOKEN` and no secrets.
Make those runs pass, and never let untrusted code reach a secret.

- Guard secret-needing steps with `if: github.event.pull_request.head.repo.full_name == github.repository`, and degrade rather than fail (`|| github.token`, or the raw test outcome).
- Secret-injecting builds (BuildKit `--secret`, registry login) must skip forks — gate **both** the `changes` job and any `always()` build job ([block fork PRs from rust image build](https://github.com/PostHog/posthog/pull/68628)).
- Comment or label only on same-repo PRs — the fork token can't write.
- To act on a fork PR with secrets/write (reviewer or label bots), use `pull_request_target`: base-repo permissions, but it must **never check out and run fork code**. That's why those workflows can't fold into a `pull_request` parent.
- First-time contributors need maintainer approval before workflows run (`action_required`) — expected.

## Timeouts

Every job sets `timeout-minutes`, sized ~2-3x observed max; gate/aggregation jobs get ~5m.
The default is 6 hours — a hung job burns paid minutes silently.
**Caveat:** `timeout-minutes` is invalid on a job that only `uses:` a reusable workflow — put the timeout inside the called workflow instead.

## Caching

Route through the shared composites rather than hand-rolling `actions/cache`: `./.github/actions/pnpm-install` (single `pnpm-<os>-<lockhash>` key, save gated to master), `astral-sh/setup-uv` with `enable-cache: true`, Depot cache via `./.github/actions/build-n-cache-image`.
One canonical key per artifact; gate saves to master or key deliberately per-ref.
PR-scoped cache writes nobody else can read just fragment the 10 GB LRU cap.

**Any job that runs `manage.py migrate` against a fresh Postgres must restore the master schema dump first**, keeping the migrate as a seconds-long top-up.
A from-scratch replay of the full migration history grows with every migration merged and already costs more than most jobs' `timeout-minutes`, so an uncached migrate is a timeout that hasn't fired yet ([agent-skills cancelled at 30 min with the checks green](https://github.com/PostHog/posthog/actions/runs/32250956659/job/96061773764)).
Copy the three steps (compute keys, `actions/cache/restore`, prime) from `ci-agent-skills.yml` for compose-stack jobs or `ci-rust-flags-integration.yml` for service-container jobs; `hogli db:restore-schema-fresh` reads `TARGET_DB` to pick the database.
A miss falls through to the full migrate, so the restore is never a correctness risk.
The only sanctioned exception is a job whose purpose is validating the migration history itself (ci-backend's `check-migrations`), where a restored dump would mask what it checks.

## Runners

`depot-ubuntu-<version>[-<vCPU>]` for build/compute-heavy jobs (the `-4`/`-8` suffix bumps CPU from the 2-vCPU default); GitHub-hosted for light jobs.
New Depot labels must be added to the allow-list in `.github/actionlint.yaml` or actionlint fails.
Details: `/depot-github-runners`.

## Draft vs ready-for-review

The merge gate is the merge queue's run on a `trunk-merge/` branch.
So a heavy suite runs its narrowed subset on drafts _and_ on ready PRs, and only the queue run takes the full matrix.
`ci-backend.yml`, `ci-frontend.yml`, `ci-storybook.yml`, and `ci-e2e-playwright.yml` all work this way.
Exclude the queue with `!startsWith(github.head_ref, 'trunk-merge/')`, or with `draft != true` since those PRs open as drafts — not with `draft == true`.

Still add `ready_for_review` to the `pull_request` types — a `no-ci` draft skips the workflow outright, and that event is what gives it a run — and make aggregator "... Tests Pass" jobs treat `skipped` as success so drafts still report.

What draft state _does_ decide is the fallback when a selection cannot be trusted (config change, oversized diff, selector crash):

- **draft → skip the suite.** Its own ready run selects again, so nothing is lost.
- **ready → full matrix.** No later run on that PR would cover it, and a narrowed run the selector can't vouch for is false confidence.

The real test is not draft-vs-ready, it is whether a later run on this PR exists to defer to.
So **draft → skip is only valid when the workflow lists `ready_for_review` in its `pull_request` types and its "... Tests Pass" aggregator treats `skipped` as success.**
Otherwise the fallback is full on drafts too: `ci-nodejs.yml` has a bare `pull_request:` trigger, so a skipped draft would never get a second run, and `ci-e2e-playwright.yml` skips drafts entirely, so there is no draft run to fall back from.

`turbo-discover.js` (`draft ? 'skip' : 'full'`) and `ci-frontend.yml`'s `fall_back` are the two reference implementations of the draft/ready split; `ci-nodejs.yml` and `ci-e2e-playwright.yml` are the reference for always-full.
Foot-gun: if the job that selects tests is cancelled mid-flight, its `mode` output is empty — normalize empty-mode **on a draft** to `skip`, or the draft grabs the full matrix and serializes the ready run behind it.

### A selector needs telemetry, or nobody knows whether it bites

A narrowing that falls back on most runs looks identical in the YAML to one that works.
The Playwright selector was eligible on 2,783 runs over two weeks and narrowed on 167 of them; the rest fell back, most often on one glob.
That is unreadable without an event, so every selector emits one to the DevEx project (347861): `posthog-ci-test-selection`, `posthog-ci-e2e-spec-selection`, `posthog-ci-jest-selection`, `posthog-ci-nodejs-selection`.

Copy the shape from `capture-jest-selection` in `ci-frontend.yml`:

- Emit **on full runs too**, tagged so they are distinguishable. They are the baseline a narrowed run is measured against.
- Give the fallback a **closed category** plus an unbounded **detail**. The category is what you group by; the detail is what tells you which glob to attack.
- Emit the counts from **every** branch of the selector, including the ones that narrow to nothing.
- `continue-on-error`, `github.run_attempt == '1'`, and the same-repo `if:` — telemetry never reds CI, never double-counts a re-run, and forks have no secret.
- Do not duplicate timings. `posthog-ci-running-time-job` already carries each job's duration; join it on `run_id`.

What this still does not answer is whether a narrowed run would have **caught** what broke.
Only backend scores that, in `tools/test_selection_verdict.py`, which reads the run's JUnit and reports recall.
The cheap oracle for the rest is the queue: the `trunk-merge/**` run tests the same code with the full suite, so a failure there whose file was reachable from the diff and was not selected is a miss, at no extra compute.

## The hourly master lane

The merge queue's `trunk-merge/**` run tests every commit before it lands, so re-running a heavy suite on the master push tests a commit that CI already covered.
Those suites skip `push` and take their master coverage — and their Trunk flaky-test baseline — from an hourly `schedule:` instead.

Crons are offset so the runs do not all fire at once, and the offsets live here rather than in the workflows:

| Workflow          | Minute |
| ----------------- | ------ |
| `ci-frontend.yml` | 7      |
| `ci-nodejs.yml`   | 13     |
| `ci-backend.yml`  | 23     |
| `ci-dagster.yml`  | 33     |
| `ci-python.yml`   | 43     |
| `ci-mcp.yml`      | 53     |

Adding a seventh: pick an unused minute, add the row, and keep the gap at ten minutes.

**Give the cron its own concurrency group.**
`cancel-in-progress` is false outside pull requests, but GitHub still keeps at most one _pending_ run per group, so a newer run replaces an older pending one.
An hourly run that shares the ref group with master pushes therefore holds the group for its whole duration while pushes queue behind it, and each new push discards the previous pending one along with whatever per-commit checks it carried.

```yaml
group: ${{ github.workflow }}-${{ github.event_name == 'schedule' && 'scheduled' || github.head_ref || github.ref }}
```

That keeps hourly runs queueing behind each other rather than stacking, and leaves push behavior untouched.
`ci-backend.yml` reaches the same place from the other side: its push arm is already keyed per SHA, so pushes never share a group with the cron.
Prefer the `'scheduled'` key when the push lane still runs real per-commit work, because a per-SHA push arm also gives up the deduplication that collapses a burst of master pushes into one run.

**The paths filter must be skipped on `schedule`, and every output it feeds must default to `true`.**
On a cron the action has nothing to diff against: it gets no `base` input, so base resolves to the default branch and equals head, and `before` is set only on push events.
It falls back to the last commit alone, so one docs-only commit narrows the hourly run to nothing and reports green having tested almost nothing — a silent failure, not a red one.
Guard the step with `if: github.event_name != 'push' && github.event_name != 'schedule'`, and give each consumed output a `|| 'true'` default.

Any _step_ that reads a filter output needs the same `schedule` arm.
`ci-dagster.yml`'s `build-matrix` is the cautionary case: without it the matrix is `[]` and the hourly run passes having run no tests.

A lane that stops producing runs is invisible to the master-red alerter: it reads run completions, so a dropped cron reads as unreadable and drops out of evaluation rather than paging.
Add every converted workflow to `SCHEDULED_GATING_WORKFLOWS` in `ci-alerts-devex.yml` in the same change, or its failures stop paging altogether.

## Backwards-compat with unrebased PRs

A workflow edit hits every open PR the instant it merges (it runs against PR-merged-with-master), but companion changes — a new dependency, file, or config — only reach a branch when it rebases.
If the workflow starts _requiring_ something unrebased branches lack, every in-flight PR fails before its tests run.
Make new behavior degrade gracefully when the prerequisite is absent, or gate it.
Roll out a new blocking lint the same way: ship `continue-on-error`, clear the inbox, promote to blocking.

## New-workflow checklist

- [ ] Triggers scoped: trigger `paths:` where the whole workflow is skippable; a required check must still fire on every PR (never paths-gate it into never dispatching).
- [ ] Canonical `concurrency:` block (per-SHA push arm if it publishes on push).
- [ ] `timeout-minutes` on every job (except reusable-caller jobs).
- [ ] Checkout names only the paths the job reads (`sparse-checkout` + cone mode off), or is shallow; bounded `1000 + blob:none` only for base diffing.
- [ ] Third-party actions SHA-pinned; Node from `.nvmrc`; `setup-uv` version pinned.
- [ ] External fetches retry (`--retry-all-errors`), except where a repeat has a side effect.
- [ ] High-volume API calls on a dedicated App token with `|| github.token` fork fallback.
- [ ] Fork PRs handled: secret-needing steps guarded with the same-repo `if:`; no secret-injecting build runs on forks.
- [ ] Caching through the shared composites; writes gated to master.
- [ ] Any job running `manage.py migrate` restores the master schema dump first, with the migrate as top-up (see Caching).
- [ ] Prod image push / deploy dispatch gated per `/gating-production-deploys`.
- [ ] `bin/hogli lint:workflows` and `actionlint` pass locally.
