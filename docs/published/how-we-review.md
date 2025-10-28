---
title: How we review PRs
sidebar: Handbook
showTitle: true
---

Almost all PRs made to PostHog repositories will need a review from another engineer. We do this because, almost every time we review a PR, we find a bug, a performance issue, unnecessary code or UX that could have been confusing. Here's how we do it:

## Have a flick through the code changes

#### What to look for:
  - Does the code fit into our coding conventions?
  - Is the code free of bugs?
  - How will the solution perform at huge scale?
    - Are the database queries scalable (do they use the right indexes)?
    - Are the migrations safe?
  - Are there tests and do they test the right things?
  - Is the solution secure?
    - Is there no leakage of data between projects/organizations?
  - Is the code properly instrumented for product analytics?
  - Is there logging for changes potentially affecting infrastructure?
  - Are analytics query changes covered by snapshot tests? Does the SQL generated make sense?

#### What _not_ to look for:
  - Syntax formatting. If we're arguing about syntax, that means we should be using a formatter or linter rule.

## Run the code yourself

#### What to look for:
  - Does the PR actually solve an issue?
    - Are we building the right thing? (We should be willing to throw away PRs or start over)
  - Does the change offer a good user experience?
  - Does the UI of the change fit into our design system?
  - Should the code be behind a feature flag?
    - If the code is behind a feature flag, do all cases work properly? (in particular, make sure the old functionality does not break)
  - Are all possible paths and inputs covered? (Try to break things!)

#### What _not_ to look for:
  - Issues unrelated to this PR. Create new, separate issues for those.

The emphasis should be on getting something out quickly. Endless review cycles sap energy and enthusiasm.
