---
name: reviewing-before-pr
description: >
  Run the one local Greptile review of a branch before its PR opens, with `hogli review`.
  Use when instructed to open a PR or a draft PR (before `gh pr create`), or before marking
  a draft ready for review when the branch never had a local review. Trigger terms: hogli review,
  greptile, local review, pre-PR review, review before opening.
---

# Reviewing before opening a PR

`hogli review` runs the same Greptile reviewer that comments on every PostHog PR, locally, against the committed branch diff.
A finding handled here is an ordinary pre-push edit; the same finding after the PR opens is a bot comment, a fix push, a stale-thread cleanup, and a CI re-run.

## When to run

- Run it **once**, right before `gh pr create`, whenever you were instructed to open a PR or a draft PR.
- Also run it once before marking a draft ready for review, if the branch never had a local review.
- Do not loop it after every push, and do not re-run it after addressing findings — each run is a paid review, and the PR bot passes over the final state anyway. `hogli review` enforces this by re-printing HEAD's existing completed review instead of starting a new one.
- Skip it for changes trivial enough for the `skip-agent-review` label.

## The flow

1. Finish the work and commit everything. Greptile reviews committed changes only; uncommitted edits are invisible to it.
2. Run `hogli review`.
3. Verify each finding's premise against the code before acting on it. Findings carry severity and confidence, and they can be false positives — rejecting one, with a reason, is a valid outcome.
4. Fix what you agree with and commit the fixes.
5. Continue the normal PR-opening flow (`hogli ci:preflight`, `gh pr create`).

## Notes

- **Exit 78 means not signed in.** Ask the user to run `greptile login` and sign in with Google, using their @posthog.com account — that is what grants access to the PostHog Greptile org, so pick "Continue with Google" in the browser window rather than creating an email-and-password account. Headless environments set `GREPTILE_API_KEY` in `.env.local` instead (an `op://` 1Password reference resolves there). Never attempt the interactive login yourself.
- **Missing CLI.** Flox activation installs it (pinned in `.flox/env/on-activate.sh`), so re-entering the environment usually fixes it. Outside flox: `brew install greptileai/tap/greptile` or `npm install -g greptile`.
- **Held-back files.** Greptile holds back files that look like they contain secrets. Leave them held back; pass `--include <path>` only when certain the file is safe to send.
- **Focus.** `--instructions "<text>"` steers the reviewer, the same way an `@greptile` comment does on a PR.
- **`--force`** starts a fresh paid review even when HEAD already has one — only when the user asks for it.
- Review behavior is configured in `.greptile/` (shared with the PR bot): `config.json` for settings, `files.json` for context files, with nested per-directory configs (`products/desktop/.greptile/` exists).
- The diff goes to Greptile's API for review. This repo is public, so that is fine for repo content — but it is one more reason not to `--include` held-back files.
