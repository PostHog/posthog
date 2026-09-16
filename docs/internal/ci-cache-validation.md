# CI cache validation

## Cache boundaries

- Livestream and Phrocs run on GitHub-hosted Ubuntu. Their `setup-go` archives use GitHub Actions cache.
- Python and Rust run on Depot runners. Their `actions/cache` calls use Depot Cache, not GitHub's cache store.
- The pnpm warmer writes two stores, one per runner backend. Its production writers remain master-only.
- Depot also configures native sccache and Turborepo caching. Neither needs another archive of its remote cache.
- Dependency caches remain lockfile-keyed. Mypy snapshots use the installed Python and mypy versions, configuration and lockfile hashes, and a run-specific suffix.
- Only successful master runs save production mypy snapshots. PRs restore the compatible prefix but never save it.
- Rust reports only allowlisted numeric counters. The full sccache report can contain an endpoint and must not be printed.
- Test-result reuse is outside this change. In particular, product backend tests retain Turbo's `--force` flag.

Depot's [cache documentation](https://depot.dev/docs/cache/overview) describes the automatic runner integration and retention policy.
Use Depot's Cache Explorer for Depot storage measurements; GitHub cache totals cannot describe those jobs.

## Baseline method

The bounded sample was collected on September 16, 2026, before workflow edits.
The query window started September 9 at 00:00 UTC and ended at collection time.
For each workflow, the sample takes the newest five successful or failed runs from the newest twenty completed runs, with no pagination.
Canceled runs are excluded, not treated as fast successes.
Rust supplied only three eligible runs in that page.
Hobby has no master trigger, so its baseline uses PR runs instead.
Python uses scheduled master runs because push runs skip the code-quality job.

Durations below come from public GitHub job-step timestamps, in seconds.
The p95 uses nearest rank; with five observations it is the maximum, not a stable population estimate.
Rust shard rows pool different workloads and are not a controlled before/after comparison.

| Workflow / job        | Runner / cache backend       | n   | Job p50 / p95 | Checkout p50 / p95 | Setup or restore p50 / p95 | Work p50 / p95   |
| --------------------- | ---------------------------- | --- | ------------- | ------------------ | -------------------------- | ---------------- |
| Livestream / test     | ubuntu-24.04 / GitHub        | 5   | 70 / 80       | 23 / 32            | Go 11 / 13                 | Lint 24 / 25     |
| Phrocs / test         | ubuntu-24.04 / GitHub        | 5   | 53 / 68       | 23 / 31            | Go 9 / 10                  | Lint 13 / 14     |
| Hobby / lint-and-test | ubuntu-24.04 / GitHub        | 5   | 49 / 52       | 2 / 4              | Go 9 / 12                  | Lint 28 / 31     |
| Hobby / build amd64   | ubuntu-24.04 / GitHub        | 5   | 39 / 44       | 2 / 2              | Go 9 / 10                  | See linked run   |
| Hobby / build arm64   | ubuntu-24.04-arm / GitHub    | 5   | 35 / 37       | 1 / 3              | Go 8 / 11                  | See linked run   |
| Python / code-quality | depot-ubuntu-24.04 / Depot   | 5   | 344 / 381     | 7 / 23             | Mypy restore 4 / 4         | Mypy 146 / 196   |
| Rust / build shards   | depot-ubuntu-22.04-4 / Depot | 24  | 242.5 / 397   | 3 / 9              | Rust cache 131 / 160       | Build 67.5 / 157 |
| Rust / lint           | depot-ubuntu-22.04-4 / Depot | 3   | 198 / 242     | 3 / 4              | Rust cache 92 / 114        | Check 9 / 9      |

Representative public evidence:

- [Livestream baseline](https://github.com/PostHog/posthog/actions/runs/35139231782): exact Go key hit; post step skips saving.
- [Phrocs baseline](https://github.com/PostHog/posthog/actions/runs/35139231734): setup-go warns that no root `go.sum` exists.
- [Hobby baseline](https://github.com/PostHog/posthog/actions/runs/35070673842): x64 build saves the key; lint-and-test cannot reserve that same key.
- [Python baseline](https://github.com/PostHog/posthog/actions/runs/35136633681): restored snapshot, mypy succeeds, save takes 19 seconds.
- [Rust baseline](https://github.com/PostHog/posthog/actions/runs/35137404432): build shards and lint restore the same Rust archive identity.
- [pnpm warmer baseline](https://github.com/PostHog/posthog/actions/runs/35137404453): each runner backend saves its own entry.

## Validation and rollback

Pre-merge cache experiments use disposable draft PRs targeting the implementation branch.
Two sequential source changes keep manifests, lockfiles, tool versions, and cache configuration fixed.
A production master-only writer may be exercised only with a throwaway-specific namespace and no production restore fallback.
Those experiment changes do not belong in the implementation diff.

Sparse checkout retains each complete Go module; neither module declares a local replacement outside its tree.
The master required-check rules do not include Livestream or Phrocs, and their existing PR filters remain unchanged.
Push filtering can be reverted independently of sparse checkout or cache keys.
Mypy can be rolled back by restoring the previous key policy; it always works without a cache.
Sccache reporting is best-effort and does not change build or test verdicts.

Hobby rolling archives, Rust target-cache removal, pnpm store changes, and uv save-policy changes need measured benefit before implementation.
Cache hits alone do not justify additional storage or transfer time.
