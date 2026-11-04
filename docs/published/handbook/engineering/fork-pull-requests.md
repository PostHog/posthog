---
title: Pull requests from forks
sidebar: Handbook
---

Backend CI runs on Depot CI, from `.depot/workflows/ci-backend.yml`, and its gate's `Backend CI on Depot / Test results` check is required on `master`.
Depot CI never runs a fork's code, so a fork pull request gets no backend run and that check stays pending.
A fork pull request cannot merge as it is.
After review, a PostHog engineer re-creates the change on a branch in this repository, which gets a Depot run and the required check.

What a fork contributor sees:

- Every other CI workflow runs on GitHub Actions and selects the same tests it selects for any other pull request.
- The backend check stays pending. Depot starts no run for a fork, and the gate fails for one if it ever does.
- Steps that need a secret skip. The same-repo `if:` guard that makes that safe is in the [CI authoring skill](https://github.com/PostHog/posthog/blob/master/.agents/skills/authoring-ci-workflows/SKILL.md).
- Visual Review needs a secret, so a fork pull request gets no Visual Review run. Each Storybook shard instead compares its screenshots with `frontend/snapshots.yml` offline. This fallback accepts only an exact pixel match. It does not know the tolerated hashes or the quarantine of Visual Review, so a flaky story can fail it. A snapshot that differs fails `Visual regression tests pass` until a maintainer updates the baseline. Without the check, the merge queue would be the first run to compare the screenshots.

Never push a fork's head to a branch inside this repository before it is reviewed.
An in-repo branch is trusted: every secret-gated step runs, with the fork's code in control of the job.
Review the fork PR as it is, then re-create it in-repo.

Re-creating keeps the contributor's credit when their commits keep them as author.
The merge queue squash-merges, and GitHub adds a `Co-authored-by` line for each commit author, which counts on their profile when the email is linked to their account.
When the re-created PR merges, a bot comments on the fork PR with a link to the merged PR and closes it.
The [`recreating-fork-prs` skill](https://github.com/PostHog/posthog/blob/master/.agents/skills/recreating-fork-prs/SKILL.md) has the steps.
