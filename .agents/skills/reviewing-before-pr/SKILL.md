---
name: reviewing-before-pr
description: >
  Review a branch with the harness's own code review skill before its PR opens, and record the pass
  in the PR description. Use when someone asks for a local review, a self-review, or a review before
  opening or pushing a PR. Trigger terms: local review, self-review, review before PR,
  review my branch, pre-PR review.
---

# Reviewing before opening a PR

Run your harness's code review over the branch diff before `gh pr create`.
A finding handled here is an ordinary pre-push edit; the same finding after the PR opens costs a bot comment, a fix push, a stale-thread cleanup, and a CI re-run.

This is the weaker pass, not a replacement for review: it reads code your own session may have written, with no independent context.
The PR review bot still reviews every PR, and human reviewers still read it.

## When to run

- When someone asks for it. Opening a PR does not call for this review by default.
- Run it **once**, on the branch as it stands, right before `gh pr create`.
- Do not loop it after every push, and do not re-run it after addressing findings.

## The flow

1. Finish the work. Commit first when the harness's review takes a branch or commit range rather than the working tree.
2. Run the harness's review over the branch diff. In Claude Code that is `/code-review`; on a stacked branch, scope it to this layer's commits against its base.
3. Verify each finding's premise against the code before acting on it. Findings can be false positives, and rejecting one with a reason is a valid outcome.
4. Fix what holds and commit the fixes.
5. Record the pass in the PR description's Agent context section: which review ran, and each finding's disposition (fixed, or rejected with the reason). The findings are otherwise invisible to reviewers, because they only appeared in the terminal.
6. Continue the normal PR-opening flow (`hogli ci:preflight`, `gh pr create`).

## Notes

- **The bot pass is separate.** A local review never substitutes for the PR review bot, so never label a PR to skip the bot on the strength of this pass.
- **Focus it when the diff has a risky part.** Most harness reviews accept instructions or a path target; pointing the review at the part you are least sure about beats a broad sweep.
