---
title: Pull requests from forks
sidebar: Handbook
---

Backend CI runs on one of two engines per pull request, decided by `.github/scripts/ci_backend_route.py`: GitHub Actions or Depot CI.
Depot CI never runs a fork's code, so the router sends every fork pull request to GitHub Actions.
The required `Django Tests Pass` check is a GitHub Actions job on every head, fork or not, and nothing about the merge queue changes for a fork.

What a fork contributor sees:

- The full backend matrix runs on GitHub Actions, as it always has.
- Depot's optional checks show as skipped. They are not required and nothing waits on them.
- Steps that need a secret skip, on both engines. The same-repo `if:` guard that makes that safe is in the [CI authoring skill](../../../../.agents/skills/authoring-ci-workflows/SKILL.md).

Never push a fork's head to a branch inside this repository to get it a Depot run.
An in-repo branch is trusted: every secret-gated step runs, with the fork's code in control of the job.
Review the fork PR as it is, and let the merge queue test it on its own branch.
