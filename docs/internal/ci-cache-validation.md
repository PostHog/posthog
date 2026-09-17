# CI cache validation

## Cache boundaries

- Livestream and Phrocs run on GitHub-hosted Ubuntu. Their `setup-go` archives use GitHub Actions cache.
- Python and Rust run on Depot runners. Their `actions/cache` calls use Depot Cache, not GitHub's cache store.
- The pnpm warmer writes two stores, one per runner backend. Its production writers remain master-only.
- Depot also configures native sccache and Turborepo caching. Neither needs another archive of its remote cache.
- Dependency caches remain lockfile-keyed. Mypy snapshots use the installed Python and mypy versions, configuration and lockfile hashes, and a run-specific suffix.
- Only successful master runs save production mypy snapshots. PRs restore the compatible prefix but never save it.
- Rust reports only allowlisted numeric counters. The full sccache report can contain an endpoint and must not be printed.
- Compilation caching must not introduce test-result reuse. Phrocs uses `go test -count=1`; product backend tests retain Turbo's `--force` flag.

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

## Controlled validation

The September 17 experiments used disposable draft PRs targeting the implementation branch: [Go #102266](https://github.com/PostHog/posthog/pull/102266), [Python #102264](https://github.com/PostHog/posthog/pull/102264), and [Rust #102265](https://github.com/PostHog/posthog/pull/102265).
Each experiment changed source twice, waiting for the first relevant workflows to finish before the second push.
Manifests, lockfiles, tool versions, and cache configuration stayed fixed between the two runs.
These are small paired observations, not population percentiles or a monthly savings estimate.

### Go checkout and dependency caches

The controls reproduce the previous full checkout alongside the proposed sparse checkout.
The Phrocs control also preserves the missing root dependency-file behavior.
All jobs passed.

| Measurement          | First run, control → proposed | Second run, control → proposed |
| -------------------- | ----------------------------- | ------------------------------ |
| Livestream checkout  | 25 → 1 s                      | 22 → 1 s                       |
| Livestream whole job | 73 → 45 s                     | 72 → 50 s                      |
| Phrocs checkout      | 22 → 1 s                      | 21 → 2 s                       |

Evidence: [first controls](https://github.com/PostHog/posthog/actions/runs/35225809001), [first Livestream](https://github.com/PostHog/posthog/actions/runs/35225808586), [first Phrocs](https://github.com/PostHog/posthog/actions/runs/35225808787), [second controls](https://github.com/PostHog/posthog/actions/runs/35226142740), [second Livestream](https://github.com/PostHog/posthog/actions/runs/35226142828), [second Phrocs](https://github.com/PostHog/posthog/actions/runs/35226142814).

Phrocs' first run saved a GitHub cache entry keyed by Go 1.25.5 and `tools/phrocs/go.sum`; the second restored that exact entry.
Both full-checkout controls warned that the root dependency file was missing.
The warm Phrocs run also exposed Go test-result reuse, so the implementation now sets `-count=1` and guards it with a workflow test.
Its warm whole-job speedup is excluded: only the checkout savings above are attributed to the implementation.

Hobby's control disabled only setup-go caching, retaining the same linter-cache settings.
For amd64 builds, existing caching took 34 seconds cold and 19 seconds warm; disabling it took 42 and 39 seconds.
Warm compilation took 1 second with the cache versus 26 seconds without it.
The [first Hobby run](https://github.com/PostHog/posthog/actions/runs/35225808642) confirmed the existing collision: amd64 build saved the Go key, then lint-and-test could not reserve it.
The [second run](https://github.com/PostHog/posthog/actions/runs/35226142526) restored that key successfully.
Disabling caching is not supported by these results; neither a new rolling archive nor a shared composite is justified by this comparison.

### Mypy snapshots

The experiment used Depot Cache, with a `validation-102264-mypy-v3-` prefix and no production fallback.
Both runs used Python 3.13.13, mypy 2.1.0, and the same configuration/lockfile hash.
Both reported `Success: no issues found in 20937 source files`.

| Measurement            | [Cold](https://github.com/PostHog/posthog/actions/runs/35225759267) | [Warm](https://github.com/PostHog/posthog/actions/runs/35226502243) |
| ---------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------- |
| Snapshot restore       | 0 s, miss                                                           | 1 s, hit                                                            |
| Typecheck              | 211 s                                                               | 27 s                                                                |
| Snapshot save          | 2 s                                                                 | 1 s                                                                 |
| Whole code-quality job | 343 s                                                               | 163 s                                                               |

The warm run restored the key ending `35225759267-1`, then saved a new key ending `35226502243-1` under the same compatible prefix.
The cold-to-warm typecheck saved 184 seconds (87%); the whole job saved 180 seconds (52%).
This demonstrates reusable, refreshable snapshots, not a guaranteed improvement over every existing warm snapshot.
Neither validation run wrote to the production namespace; its master-only writer remained disabled on both PRs.

### Rust object reuse

The existing native sccache reused compiled objects across the [first source change](https://github.com/PostHog/posthog/actions/runs/35225763945/job/105217209738) and [second source change](https://github.com/PostHog/posthog/actions/runs/35226841404/job/105220913137).
For the `cymbal hogvm` build shard:

| Measurement          | First run | Second run |
| -------------------- | --------- | ---------- |
| Compile requests     | 287       | 287        |
| Cache hits           | 170       | 239        |
| Cache misses         | 74        | 5          |
| Non-cacheable calls  | 41        | 41         |
| Rust archive restore | 106 s     | 125 s      |
| Cargo build          | 212 s     | 126 s      |

The reports contained only the numeric counters, and both builds passed.
This confirms existing object reuse; the instrumentation does not create the speedup.
The experiment did not disable the target archive, so it does not establish the benefit of removing it.
The archive policy stays unchanged.

### Other cache layers

A [bounded backend test log](https://github.com/PostHog/posthog/actions/runs/34274998877/job/102226327624) reports native Turbo remote caching enabled, but `cache bypass, force executing` and zero cached test tasks.
That behavior remains unchanged.
No storage-capacity conclusion comes from GitHub cache totals, and no pnpm, Turbo, or uv performance improvement is claimed.

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
