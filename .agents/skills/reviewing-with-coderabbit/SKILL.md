---
name: reviewing-with-coderabbit
description: >
  Disabled. CodeRabbit is retired on this repository in favor of PostHog Review (ReviewHog),
  so there is no local CodeRabbit pass to run before `gh pr create`.
  When invoked, or when a prompt or template still mentions a CodeRabbit CLI pass, do nothing and continue
  the task. Not for a person's own request to review a branch. Trigger terms: coderabbit, cr review,
  CodeRabbit CLI.
---

# Reviewing with CodeRabbit (disabled)

This skill is switched off.
PostHog Review (ReviewHog) reviews pull requests automatically.
The Code review settings of the project that owns the repository and the author's own choices control which pull requests get an automatic Flash review.
For the setup requirements, see the [ReviewHog architecture guide](../../../products/review_hog/ARCHITECTURE.md#entry-point-commands--configuration).
An eligible person can also add the `reviewhog` label to request a review.

When this skill is invoked, or an instruction asks for a CodeRabbit CLI pass:

- Do not run `cr`, `coderabbit`, or `cr auth login`. The sign-in command opens a browser tab.
- Do not run `/code-review`, review subagents, or a fan-out over the diff in its place unless a person asked for that review. An agent review of a large diff bills a person's tokens.
- Record nothing about a skipped pass in the PR description.
- Continue the normal flow: `hogli ci:preflight`, then `gh pr create`.

The previous flow is in this file's git history.
