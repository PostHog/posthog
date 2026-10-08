---
name: reviewing-with-coderabbit
description: >
  Disabled. CodeRabbit is retired on this repository in favor of PostHog Review (`.github/review-hog.yml`),
  so there is no local CodeRabbit pass to run before `gh pr create`.
  When invoked, or when a prompt or template still mentions a CodeRabbit CLI pass, do nothing and continue
  the task. Not for a person's own request to review a branch. Trigger terms: coderabbit, cr review,
  CodeRabbit CLI.
---

# Reviewing with CodeRabbit (disabled)

This skill is switched off.
PostHog Review (ReviewHog) reviews pull requests automatically in repositories that commit `.github/review-hog.yml`, for the authors and events that file allows.
An eligible person can also add the `reviewhog` label to request a review.

When this skill is invoked, or an instruction asks for a CodeRabbit CLI pass:

- Do not run `cr`, `coderabbit`, or `cr auth login`. The sign-in command opens a browser tab.
- Do not run `/code-review`, review subagents, or a fan-out over the diff in its place unless a person asked for that review. An agent review of a large diff bills a person's tokens.
- Record nothing about a skipped pass in the PR description.
- Continue the normal flow: `hogli ci:preflight`, then `gh pr create`.

The previous flow is in this file's git history.
