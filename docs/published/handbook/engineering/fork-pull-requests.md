---
title: Pull requests from forks
sidebar: Handbook
---

Backend CI runs on one of two engines per pull request, decided by `.github/scripts/ci_backend_route.py`: GitHub Actions or Depot CI.
Depot CI never runs a fork's code, so the router sends every fork pull request to GitHub Actions.
The required `Django Tests Pass` check is a GitHub Actions job on every head, fork or not, and nothing about the merge queue changes for a fork.
For in-repository PRs, an unreadable prior routing decision stops CI instead of switching engines.
The Depot relay matches the PR event's named wait check and reads only that Depot workflow's verdict; it never starts GitHub tests after a timeout.

What a fork contributor sees:

- Backend CI runs on GitHub Actions, as it always has, and selects the same tests it selects for any other pull request.
- Depot's optional checks show as skipped. They are not required and nothing waits on them.
- Steps that need a secret skip, on both engines. The same-repo `if:` guard that makes that safe is in the [CI authoring skill](https://github.com/PostHog/posthog/blob/master/.agents/skills/authoring-ci-workflows/SKILL.md).
- Visual Review needs a secret, so a fork pull request gets no Visual Review run. Each Storybook shard instead compares its screenshots with `frontend/snapshots.yml` offline. This fallback accepts only an exact pixel match. It does not know the tolerated hashes or the quarantine of Visual Review, so a flaky story can fail it. A snapshot that differs fails `Visual regression tests pass` until a maintainer updates the baseline. Without the check, the merge queue would be the first run to compare the screenshots.

Never push a fork's head to a branch inside this repository to get it a Depot run.
An in-repo branch is trusted: every secret-gated step runs, with the fork's code in control of the job.
Review the fork PR as it is, and let the merge queue test it on its own branch.

## Backend failures on Depot

The GitHub `Django Tests Pass` relay follows the selected Depot workflow, including its latest attempts.
A failed Repo checks or OpenAPI prerequisite explains a cancelled gate immediately. A job failure alone
does not establish determinism: the diagnostic collector checks the prerequisite's explicit classifier
step. OpenAPI also needs explicit generated-file drift evidence because its check step includes
network operations. Confirmed deterministic failures need a fix; downstream cancellations are expected. Other
failures remain of unknown retryability without retry or flakiness evidence. A fresh commit is the
retry path that requires no Depot account, and always goes through GitHub's router. Re-running the
GitHub relay alone does not retry Depot. Do not use the engine override label as routine recovery.

Detailed diagnostics use request/report artifacts between the relay and `Backend Depot diagnostics`.
That `workflow_run` collector executes an immutable default-branch revision, with no PR checkout,
PR dependencies, or suggested diagnosis commands. It validates the GitHub handoff, repository, PR
head, Depot merge SHA, organization, workflow and latest attempt before publishing bounded, redacted
excerpts. AI diagnosis prose does not establish failure or flakiness. Missing or malformed diagnostics
leave the original verdict unchanged and are reported as unavailable. Neither diagnostics nor a
timeout can start tests on the other engine. Rollback keeps `CI_BACKEND_DEPOT_PERCENT` set to `0`;
never delete the variable.

Activation requires the collector on the default branch and an approved `DEPOT_CI_CANCEL_TOKEN`
available in its isolated GitHub job. A Depot secret's repository selector does not establish the
token's own API permissions or make it available to GitHub. There is no fallback to `DEPOT_TOKEN`.
An organization-wide token retains organization-wide access even in this isolated job; verify its
scope before activation. Without the credential, detailed diagnostics are unavailable. Unrebased
PRs without the diagnostic reader retain their original verdict and receive an explicit availability
message.
