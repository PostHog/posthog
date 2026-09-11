---
title: Pull requests from forks
sidebar: Handbook
---

Once Depot CI posts the required `Django Tests Pass` check (the ci-backend cutover), that check exists only for branches inside the PostHog/posthog repository.
A pull request from a fork keeps its GitHub Actions runs but gets no Depot run, so the check never appears on the fork's head.

Two rules keep fork PRs mergeable:

- **The merge queue gates on its own branch.**
  Trunk tests every merge on a `trunk-merge/**` branch inside this repository, so the required check runs there for every PR, fork or not.
- **A maintainer re-pushes the branch in-repo when the PR needs a full run before the queue.**
  Push the fork's head to a `contrib/` branch here and open a PR from it.
  Reviewers then see the same checks an in-repo PR gets.

  ```bash
  git fetch origin pull/<n>/head && git push origin FETCH_HEAD:refs/heads/contrib/<short-name>
  ```

Fork PRs receive no secrets on either engine, so steps that need one skip on forks.
The same-repo `if:` guard that makes that safe is in the [CI authoring skill](../../../../.agents/skills/authoring-ci-workflows/SKILL.md).
