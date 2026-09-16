# Backend CI routing between GitHub Actions and Depot CI

Each Backend CI event runs on exactly one engine, and GitHub Actions picks it.
Its `changes` job outputs `engine`. The `Hand off backend tests to Depot CI` job
succeeds only when that output is `depot` and is skipped otherwise. Depot CI's
first job polls that check run on the head commit and runs the tests only when it
concluded `success`. Nothing runs on Depot that GitHub Actions did not hand off,
so the tests and their side effects (snapshot commits, uploads, comment posters,
telemetry) never run twice.

## The hand-off wait

- Depot's wait job reads `commits/<sha>/check-runs`, filtered to the hand-off
  check name and the GitHub Actions app, for up to 10 minutes. It sends an ETag,
  so an unchanged answer is a 304 and costs no rate limit.
- Only a check run that started after the event's `updated_at` counts. A `no-ci`
  draft marked ready keeps its SHA, and with it the earlier skipped hand-off.
- Any conclusion other than `success`, a 401 or 403, or the deadline means Depot
  runs nothing. There is no fallback in either direction.
- Manual dispatches run on the engine that received them. Fork PRs never run on
  Depot, whatever the hand-off says.

## What the Depot workflow exposes

The wait job (`sample`) outputs `sampled` and `side_effects`, both true only when
GitHub Actions handed the event off. Every ported side effect gates on
`needs.sample.outputs.side_effects`, so it runs exactly when Depot runs the tests.

The required `Django Tests Pass` check stays a GitHub Actions job. Branch
protection does not change during the rollout.

Hourly scheduling and `mirror-schema-cache` remain on GitHub Actions.
