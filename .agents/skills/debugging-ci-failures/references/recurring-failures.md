# Failure families that recur

Master goes red for the same handful of reasons.
Each family below has fired repeatedly on `PostHog/posthog` between January and August 2026, so a failure matching one is evidence about which verdict is likely, not proof of it.
Confirm against the current run before you report.

The families exist to stop two specific mistakes: calling a months-old baseline a new regression, and pinning a regression on the commit that happened to be at the head when it first showed red.

## Recurrence rate is the classifier

A family that has fired at a low rate for weeks is infrastructure or a flaky test, whatever it looks like in one run.
The webkit `page.goto` timeouts in Storybook ran at roughly 5 to 9 percent for 114 days.
Depot runner communication loss ran as a background rate for four months and then stopped on its own.
Neither was ever a regression from the commit that happened to be red at the time.

Before calling a failure new, check when its job last passed and whether the same failure appears on unrelated branches.
"New today" and "has been failing quietly since April" are different verdicts, and the second one is more common than it looks.

## The first red commit is often not the culprit

Three separate causes produce a run that looks like a regression while the head commit is innocent.

**A shard layout change.** Test-timing rebalances move which tests run first in a shard. A test that was safe in position 40 can poison the whole shard from position 1, because the first test is what triggers lazy imports. The failure appears on every branch that runs that shard, including PRs that touch nothing related.

**An external version moved.** A `latest` tag on a toolchain, a base image, or a hosted model endpoint changes under a pinned requirement. `uv:latest` broke a `required-version` pin this way; a ClickHouse minor bump produced golden-file drift.

**A test that depends on ambient environment.** A test that passes locally and on most runners fails where an environment variable happens to be set, or where a service is reachable that usually is not.

The tell for all three is spread: the same failure on branches with unrelated diffs. When you see that, stop bisecting master and look for what changed underneath every branch at once.

## Gate jobs report `cancelled` as failure

An aggregating gate job (`Django Tests Pass`, `Dagster Tests Pass`, `Rust Tests Pass`, `Frontend Tests Pass`) fails when a shard it waits on is cancelled, not only when a shard fails.
This produced a 48 percent failure rate on one gate for 57 days without a single broken test behind it.

When a gate is the only red job, read the shards it depends on before you read anything else.
If every shard is green or cancelled, the verdict is the gate, and no code change fixes it.

## Infrastructure families with no code fix

These recur, resolve on their own, and are not worth a culprit hunt. Name the component, say no code change fixes it, and stop.

- GitHub artifact API transients: upload 403 or `ETIMEDOUT`, download 500. Seen across 175 days.
- Registry and download failures: Docker Hub login rejected with valid credentials, Docker push failures at a few percent, Rust toolchain fetches from `static.rust-lang.org`, Python CDN 500s.
- Depot runner faults: communication loss mid-run, gRPC keepalive timeouts on image builds, runners dying on specific shards.
- Container startup in product tests: a service container that never becomes ready, most often Temporal.

Check <https://www.githubstatus.com/> and <https://status.depot.dev/> when several of these appear at once, per the parent skill.

## Storybook drift is usually real and usually a UI merge

A UI change that alters shared chrome fails many Storybook shards at once, within a run or two of merging.
Settings navigation reorders have taken out seven or more shards in a single run.

Many shards failing together, right after a UI merge, is a real regression: the baselines need approval, not a rerun.
One shard failing intermittently over days is the flaky family above.
The distinction is how many shards and how suddenly.

## Deterministic test failures after a default changed

A changed default, limit, or fixture that ships without its test update fails every run identically from one commit onward.
This is the family where pinning the culprit commit is both possible and useful, because the fix is small and the boundary is sharp.

Identical error text on every run, starting at a commit that touched the relevant default, is the signature.
