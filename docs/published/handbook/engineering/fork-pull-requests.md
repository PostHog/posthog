---
title: Pull requests from forks
sidebar: Handbook
---

Backend CI runs on one of two engines per pull request, decided by `.github/scripts/ci_backend_route.py`: GitHub Actions or Depot CI.
Depot CI never runs a fork's code, so the router sends every fork pull request to GitHub Actions.
The required `Django Tests Pass` check is a GitHub Actions job on every head, fork or not, and nothing about the merge queue changes for a fork.

What a fork contributor sees:

- Backend CI runs on GitHub Actions, as it always has, and selects the same tests it selects for any other pull request.
- Depot's optional checks show as skipped. They are not required and nothing waits on them.
- Steps that need a secret skip, on both engines. The same-repo `if:` guard that makes that safe is in the [CI authoring skill](https://github.com/PostHog/posthog/blob/master/.agents/skills/authoring-ci-workflows/SKILL.md).
- Visual Review needs a secret, so a fork pull request gets no Visual Review run. Each Storybook shard instead compares its screenshots with `frontend/snapshots.yml` offline. This fallback accepts only an exact pixel match. It does not know the tolerated hashes or the quarantine of Visual Review, so a flaky story can fail it. A snapshot that differs fails `Visual regression tests pass` until a maintainer updates the baseline. Without the check, the merge queue would be the first run to compare the screenshots.

Never push a fork's head to a branch inside this repository to get it a Depot run.
An in-repo branch is trusted: every secret-gated step runs, with the fork's code in control of the job.
Review the fork PR as it is, and let the merge queue test it on its own branch.
