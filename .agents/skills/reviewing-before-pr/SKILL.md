---
name: reviewing-before-pr
description: >
  Run one local Greptile review of a branch before its PR opens, with `hogli review`.
  Opt-in: it needs a seat on PostHog's Greptile workspace, which most people do not have yet,
  so use it only when someone asks for a local Greptile review by name. Trigger terms:
  hogli review, greptile, local review, pre-PR review.
---

# Reviewing before opening a PR

`hogli review` runs the same Greptile reviewer that comments on every PostHog PR, locally, against the committed branch diff.
A finding handled here is an ordinary pre-push edit; the same finding after the PR opens is a bot comment, a fix push, a stale-thread cleanup, and a CI re-run.

## When to run

- Only when someone asks for it. A Greptile seat is per-person and hand-granted today, so opening a PR does not call for this review by default — the PR bot still reviews every PR.
- When asked, run it **once**, on the committed branch, right before `gh pr create`.
- Do not loop it after every push, and do not re-run it after addressing findings — each run is a paid review, and the PR bot passes over the final state anyway. `hogli review` enforces this by re-printing HEAD's existing completed review instead of starting a new one.
- Skip it for changes trivial enough for the `skip-agent-review` label.

## The flow

1. Finish the work and commit everything. Greptile reviews committed changes only; uncommitted edits are invisible to it.
2. Run `hogli review`.
3. Verify each finding's premise against the code before acting on it. Findings carry severity and confidence, and they can be false positives — rejecting one, with a reason, is a valid outcome.
4. Fix what you agree with and commit the fixes.
5. Skip the duplicate bot review. Run `hogli review --check` (on a stacked branch, `-b <base>` scopes it to this layer's commits): it exits 0 when any commit on the branch has a completed review — that is, the local loop ran, even if fix commits landed after it. On exit 0, open the PR with `--label no-greptile`. On a nonzero exit (no local review ever ran on this branch, or signed out), omit the label and let the bot review.
6. Either way, record the local review in the PR description's Agent context section: the review ID and each finding's disposition (fixed, or rejected with the reason). The findings are otherwise invisible to reviewers — they only appeared in the terminal.
7. Continue the normal PR-opening flow (`hogli ci:preflight`, `gh pr create`).

## Fallback without Greptile access

When `hogli review` cannot run (exit 78 with no way to sign in, or no CLI in a sandbox), do not block the PR on it.
Run your harness's own review instead (Claude Code: `/code-review`) over the branch diff, and triage its findings through the same flow: verify each premise, fix what holds, commit.
Treat it as the weaker pass — it reviews code your own session may have written, with no independent context — so verify premises strictly.
A fallback review never earns the `no-greptile` label: `hogli review --check` stays nonzero without a Greptile review, so the gate enforces this on its own and the bot reviews the PR as usual.
Say in the PR description's receipt that the local pass was the harness fallback, so reviewers know the independent review is still the bot's.

## Notes

- **Exit 78 means not signed in.** Ask the user to run `greptile login` and sign in with Google, using their @posthog.com account — that is what grants access to the PostHog Greptile org, so pick "Continue with Google" in the browser window rather than creating an email-and-password account. Headless environments set `GREPTILE_API_KEY` in `.env.local` instead (see `.env.local.example`). Never attempt the interactive login yourself; when sign-in is not available, use the fallback above.
- **Missing CLI.** Flox activation installs the version pinned in `.flox/env/on-activate.sh` into the machine-shared store `~/.config/posthog/tools/greptile/`, so re-entering the environment usually fixes it. Outside flox: `brew install greptileai/tap/greptile` or `npm install -g greptile`.
- **Held-back files.** Greptile holds back files that look like they contain secrets. Leave them held back; pass `--include <path>` only when certain the file is safe to send.
- **Focus.** `--instructions "<text>"` steers the reviewer, the same way an `@greptile` comment does on a PR.
- **`--force`** starts a fresh paid review even when HEAD already has one — only when the user asks for it.
- **The `no-greptile` label** works because `.greptile/config.json` lists it in `disabledLabels`. Apply it only through the `--check` gate above — never to silence a bot review you have not run locally. When in doubt, leave the label off; the default is that the bot reviews.
- Review behavior is configured in `.greptile/` (shared with the PR bot): `config.json` for settings, `files.json` for context files, with nested per-directory configs (`products/desktop/.greptile/` exists).
- The diff goes to Greptile's API for review. This repo is public, so that is fine for repo content — but it is one more reason not to `--include` held-back files.
