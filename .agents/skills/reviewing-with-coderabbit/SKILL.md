---
name: reviewing-with-coderabbit
description: >
  Paused: the CodeRabbit local review is not running yet. Use whenever a review of a branch is asked for
  (a local review, a self-review, a CodeRabbit review, a pre-PR review) or before `gh pr create`, so the
  agent skips the CodeRabbit CLI without substituting an agent review. Trigger terms: coderabbit,
  cr review, local review, self-review, review my branch, pre-PR review.
---

# Reviewing with CodeRabbit (paused)

The CodeRabbit rollout has not started, so this skill does nothing for now.
The full flow returns when the rollout begins; the git history of this file holds it.

## While paused

- Do not run any `coderabbit` or `cr` command, including `cr review`, `cr auth login`, `cr auth status`, and `cr doctor`.
  A run on a machine that is not signed in opens a browser sign-in tab for the person at the keyboard.
- Do not run `/code-review`, review subagents, or a fan-out over the diff in its place.
  An agent review of a large diff bills a person's tokens and can reach hundreds of dollars on one branch.
- Continue the normal flow: `hogli ci:preflight`, then `gh pr create`.
- Under Agent context in the PR description, write that the CodeRabbit pass is paused and the PR opened without a local pass.
