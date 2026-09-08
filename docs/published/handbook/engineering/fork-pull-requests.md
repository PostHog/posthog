---
title: Pull requests from forks
sidebar: Handbook
---

The required backend check on `master` is posted by Depot CI, which runs only branches that live in the PostHog/posthog repository.
A pull request from a fork still gets its GitHub Actions runs, but no Depot run, so the required check never appears on the fork's own head.

Two rules keep fork PRs mergeable anyway:

- **The merge queue gates on its own branch.**
  Trunk tests every merge on a `trunk-merge/**` branch inside this repository, so the required check runs there for every PR, fork or not.
  A fork PR that is reviewed and enqueued lands the same way as any other.
- **A maintainer re-pushes the branch in-repo when the PR needs a full run before the queue.**
  Push the fork's head to a `contrib/` branch here and open a PR from it.
  Reviewers then see the same checks an in-repo PR gets, and the queue takes the in-repo PR.

  ```bash
  gh pr checkout <n>
  git push origin HEAD:refs/heads/contrib/<short-name>
  ```

Fork PRs receive no secrets on either engine.
Steps that need one skip or degrade on forks; the same-repo `if:` guard in the workflows is what keeps that safe, so keep it on every new secret-reading step.
