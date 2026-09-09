---
name: reviewing-with-coderabbit
description: >
  Run a CodeRabbit review over the branch from the terminal, with the `coderabbit` CLI, and record the
  pass in the PR description. Use only when someone asks for a review: a local review, a self-review, a
  CodeRabbit review, or a review of a branch before its PR opens. A task that says to build something and
  open a PR does not ask for a review, so do not load this skill for one.
  Trigger terms: coderabbit, cr review, local review, self-review, review my branch, pre-PR review.
---

# Reviewing with CodeRabbit

The CodeRabbit CLI runs the same review the bot runs, in the terminal, against the branch as it stands.
A finding handled here is an ordinary pre-push edit.
The same finding after the PR opens costs a bot comment, a fix push, a stale-thread cleanup, and a CI re-run.

The review is metered.
The free tier allows 3 reviews per hour, and the usage-based add-on bills per file.
Run it once, on the branch as it stands.
Do not loop it after every push, and do not re-run it after you address findings.

## Never substitute an agent review

If the CLI is absent, signed out, or rate limited, **say so and stop**.

Do not run `/code-review`.
Do not spawn review subagents.
Do not fan out over the diff.
An agent review of a large diff costs orders of magnitude more than the CodeRabbit review it replaces, and nobody asked for that spend.
The correct outcome is a PR that opens without a local pass.

## Setup

```sh
brew install coderabbit          # or: curl -fsSL https://cli.coderabbit.ai/install.sh | sh
cr auth login                    # opens a browser; use the @posthog.com account
cr auth status                   # confirms the session and the organization
```

`cr doctor` reports what is wrong and exits non-zero when a check fails.

## The flow

1. Finish the work and commit.
   The review reads the branch, so uncommitted edits need the matching change-scope flag (`cr review --help` lists them).
2. Run the review, scoped to the branch's base:

   ```sh
   cr review --prompt-only --base master
   ```

   `--prompt-only` prints plain text for an agent to read.
   Drop it when a person reads the output.
   On a stacked branch, pass the layer's own base rather than `master`, so the review covers this layer alone.

3. Verify each finding's premise against the code before you act on it.
   Findings can be false positives, and rejecting one with a reason is a valid outcome.
4. Fix what holds, and commit the fixes.
5. Record the pass in the PR description's Agent context section: that the CodeRabbit CLI ran, and each finding's disposition, fixed or rejected with the reason.
   The findings are otherwise invisible, because they only appeared in the terminal.
6. Continue the normal flow: `hogli ci:preflight`, then `gh pr create`.

## Notes

- **The CLI reads `.coderabbit.yaml`.**
  The repository config maps our own guideline documents to the paths they govern, so a local finding cites the same criteria the bot would cite.
  Sanity-check a surprising finding against that mapping before you treat it as a rule.
- **The bot does not review on its own.**
  `auto_review` is off in `.coderabbit.yaml`, so no review posts when a PR opens.
  Comment `@coderabbitai review` on the PR to ask for one.
- **This is the weaker pass.**
  It reads code your own session may have written, with no independent context.
  It never replaces human review.
- **Point it at the risky part.**
  When one part of the diff is the part you are least sure about, review that path rather than sweeping the branch.
