---
name: authoring-ci-workflows
description: >
  Use when adding or editing a GitHub Actions workflow, composite action, or reusable workflow under `.github/` — new CI jobs, triggers, matrices, checkout/clone tuning, action pinning, GitHub App token auth, concurrency groups, `timeout-minutes`, `paths` filters, caching, or runner choice.
  Covers PostHog's workflow-authoring conventions and the reasons behind them: the 500-runs/10s dispatch cap, shallow vs full clone, per-SHA push concurrency, dedicated App-token rate-limit buckets, and fork-safe secrets on a public repo.
  Points to the linters (`bin/hogli lint:workflows`, actionlint) that enforce the mechanical rules, and to the narrower skills for production deploys, secrets, and Depot runners.
  Not for debugging red CI (use debugging-ci-failures) or wiring a new secret end to end (use managing-github-actions-secrets).
---

# Authoring CI workflows

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
Today that's: `timeout-minutes` on every job, the canonical PR concurrency block, `dorny/paths-filter` negation safety, justification for full-depth checkouts, cache-write gating, semgrep service coverage, and generic GHA correctness (bad `secrets.*` / `needs:` refs, deprecated `::set-output`, unknown runner labels).
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
    merge_group:
    workflow_dispatch:
  ```

  `merge_group:` currently no-ops — no merge queue is enabled right now — but it's harmless and forward-compatible, so keep it on merge-gate workflows for when a queue returns.

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
- Use `github.ref` as the fallback, never `github.run_id` — `run_id` is unique per run, so it silently gives every push its own group and dedup is lost.
- Publish-on-push workflows must not let two master pushes race `:latest` / a deploy dispatch.
  Key the push arm per-SHA (see `ci-backend.yml`):

  ```yaml
  group: ${{ github.workflow }}-${{ github.event_name == 'push' && github.sha || github.head_ref || github.ref }}
  ```

## Checkout / clone — shallow by default

Full clones are slow and hang on degraded runners; blobs dominate clone size and are lazily fetchable.
Default to shallow; go deep only for real merge-base or version math, and even then bound the depth and filter blobs.

- **Default:** plain `actions/checkout` (depth 1). Add nothing.
- **Diffing against the PR base:** bounded depth + blobless, then an explicit, scoped fetch (the sanctioned pattern, from `ci-backend.yml`):

  ```yaml
  - uses: actions/checkout@<sha> # v6
    with:
      fetch-depth: 1000
      filter: blob:none
  - name: Fetch PR base for affected diff
    if: github.event_name == 'pull_request'
    env:
      BASE_REF: ${{ github.event.pull_request.base.ref }}
    run: git fetch --no-tags --depth=1000 --filter=blob:none origin "$BASE_REF:refs/remotes/origin/$BASE_REF"
  ```

- **One file (e.g. `.nvmrc` before `setup-node`):** `sparse-checkout` it instead of cloning the repo.
- **Foot-gun:** `git fetch --deepen=N` with **no refspec** falls back to the wildcard `refs/heads/*` and pulls _every branch_.
  Always pass an explicit, `--no-tags`, `--filter=blob:none` refspec scoped to the base ref.
  (Bumping `actions/checkout`'s own `fetch-depth` is safe — it uses a scoped `refs/pull/N/merge` refspec.)
- The linter rejects `fetch-depth: 0` unless you add `filter: blob:none`, use `sparse-checkout`, or justify it with `# hogli-lint: allow-full-depth-checkout -- <reason>`.
  Genuinely full-history jobs: repo mirroring (`foss-sync.yml`), tag/submodule version math (`release-cli.yml`).
  Most base-diff jobs should use bounded `1000 + blob:none`.

## Pinning and tool versions

- **Pin every third-party action to a full 40-char commit SHA** with a `# vX.Y.Z` comment.
  A moved tag can ship malicious code; pinning is also reproducible and skips a per-run GitHub-API version lookup.
  The only sanctioned exception is a debug-only action.
  In-repo composites use a local path with no ref (`uses: ./.github/actions/pnpm-install`).
- **Node version comes from `.nvmrc`** — `node-version-file: .nvmrc`, never a hardcoded `node-version:`.
  Sparse-checkout `.nvmrc` if the job has no checkout.
- **Pin `setup-uv`'s `version:`** — an unpinned `setup-uv` calls the GitHub API on every job and burns the rate limit.

## Tokens — dedicated App tokens for high-volume calls

`GITHUB_TOKEN` shares one ~15k req/hr bucket across every job of every run in the repo; it goes hot at merge peaks and change-detection jobs fail before real work starts.
A dedicated GitHub App installation is its own bucket — rate-limit headroom plus blast-radius isolation.

```yaml
- uses: actions/create-github-app-token@<sha> # v3.1.1
  id: app-token
  # forks can't read org secrets — fall back to github.token
  if: github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository
  with:
    client-id: ${{ secrets.GH_APP_POSTHOG_PATHS_FILTER_APP_ID }}
    private-key: ${{ secrets.GH_APP_POSTHOG_PATHS_FILTER_PRIVATE_KEY }}
  # consumer step:
  token: ${{ steps.app-token.outputs.token || github.token }}
```

- **Right-size, don't over-isolate.** One heavy consumer (change detection on a hot matrix) deserves its own app; a long tail of light workflows can share `GITHUB_TOKEN`.
  Convention: `GH_APP_<PURPOSE>_APP_ID` + `GH_APP_<PURPOSE>_PRIVATE_KEY`.
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

## Runners

`depot-ubuntu-<version>[-<vCPU>]` for build/compute-heavy jobs (the `-4`/`-8` suffix bumps CPU from the 2-vCPU default); GitHub-hosted for light jobs.
New Depot labels must be added to the allow-list in `.github/actionlint.yaml` or actionlint fails.
Details: `/depot-github-runners`.

## Draft vs ready-for-review

Most commits land before a PR is marked ready, and drafts can't merge — so heavy suites should run a narrowed subset on drafts and the full matrix on `ready_for_review` (the merge gate).
Add `ready_for_review` to the `pull_request` types, and make aggregator "... Tests Pass" jobs treat `skipped` as success so drafts still report.
Foot-gun: if a `select-tests` job is cancelled mid-flight, its `mode` output is empty — normalize empty-mode **on a draft** to `skip`, or the draft grabs the full matrix and serializes the ready run behind it.

## Backwards-compat with unrebased PRs

A workflow edit hits every open PR the instant it merges (it runs against PR-merged-with-master), but companion changes — a new dependency, file, or config — only reach a branch when it rebases.
If the workflow starts _requiring_ something unrebased branches lack, every in-flight PR fails before its tests run.
Make new behavior degrade gracefully when the prerequisite is absent, or gate it.
Roll out a new blocking lint the same way: ship `continue-on-error`, clear the inbox, promote to blocking.

## New-workflow checklist

- [ ] Triggers scoped: trigger `paths:` where the whole workflow is skippable; a required check must still fire on every PR (never paths-gate it into never dispatching).
- [ ] Canonical `concurrency:` block (per-SHA push arm if it publishes on push).
- [ ] `timeout-minutes` on every job (except reusable-caller jobs).
- [ ] Checkout is shallow, or bounded `1000 + blob:none` for base diffing.
- [ ] Third-party actions SHA-pinned; Node from `.nvmrc`; `setup-uv` version pinned.
- [ ] High-volume API calls on a dedicated App token with `|| github.token` fork fallback.
- [ ] Fork PRs handled: secret-needing steps guarded with the same-repo `if:`; no secret-injecting build runs on forks.
- [ ] Caching through the shared composites; writes gated to master.
- [ ] Prod image push / deploy dispatch gated per `/gating-production-deploys`.
- [ ] `bin/hogli lint:workflows` and `actionlint` pass locally.
