---
name: syncing-desktop-fork
description: Merge PostHog/posthog master into the desktop fork branch (mariusandra/posthog, branch `desktop`), resolving conflicts and adapting incoming frontend changes for the desktop app. Use when running the daily desktop fork sync, when the desktop-sync workflow needs conflict resolution, or when asked to sync the desktop branch with upstream master. Trigger terms: desktop sync, fork sync, merge master into desktop, desktop-sync workflow.
---

# Syncing the desktop fork with upstream master

The PostHog desktop app lives on the `desktop` branch of the fork `mariusandra/posthog` (default branch there).
It is upstream `PostHog/posthog` master plus the desktop changes (`products/desktop/`, scene-awareness work in `frontend/`).
The `.github/workflows/desktop-sync.yml` workflow merges upstream master into it daily; this skill is the procedure, both for that workflow's automated agent step (OpenAI Codex CLI) and for running a sync by hand.

## The merge

```sh
git remote add upstream https://github.com/PostHog/posthog.git 2>/dev/null || true
git fetch --filter=blob:none upstream master
git merge --no-edit upstream/master
```

If the merge is already in progress (CI invokes the agent only after a conflicted `git merge`), skip straight to conflict resolution — never `git merge --abort` and never reset the branch.

## Resolving conflicts

- Upstream master is the source of truth for everything the desktop branch does not deliberately change. For conflicts in files the desktop branch never touched meaningfully, take upstream's side.
- `products/desktop/**`, `.github/workflows/desktop-sync.yml`, `.github/workflows/desktop-release.yml`, and this skill are desktop-owned: keep our side, then re-apply whatever upstream's change was trying to do if it also applies here (e.g. a repo-wide actions version bump).
- For shared frontend files the desktop branch modified (scene-awareness wiring, kea logic changes): merge both intents. Never silently drop an upstream change; if the two sides are genuinely incompatible, prefer upstream behavior for the web app and re-express the desktop need on top of it.
- Regenerate rather than hand-merge generated files (lockfiles, generated types): for `pnpm-lock.yaml` take upstream's version, then run `pnpm install` if the desktop branch adds dependencies of its own (it currently does not — `products/desktop` uses only catalog and external deps).
- Finish the merge with a normal merge commit. Verify nothing is left over: `git diff --check` is clean, no `<<<<<<<` markers in tracked files, and `.git/MERGE_HEAD` is gone after committing.

## Adapting incoming changes: tab awareness

This branch is "scene aware": scene logics are attached to the scene logic so they stay mounted and awake while their tab is in the background.
Not all scenes are converted yet, and the long-term intent is that every scene — including new scenes arriving from upstream — is tab aware.

The conversion playbook is not written yet.
Until it is: do not attempt conversions during sync.
Instead, list any new or substantially reworked scenes that arrived from upstream in the sync commit message body (`Scenes needing tab-awareness review: ...`) so they can be converted deliberately later.

## Verifying

Only desktop and frontend correctness matter on this fork; backend, e2e, and playwright suites are deliberately not run.

```sh
pnpm install --frozen-lockfile --filter=@posthog/desktop
pnpm --filter=@posthog/desktop test
```

If the merge touched shared frontend files the desktop branch also modifies, additionally typecheck: `pnpm install --frozen-lockfile && pnpm --filter=@posthog/frontend typescript:check`.
Fix failures the merge introduced; if a failure clearly pre-exists on upstream master, note it in the commit message instead of chasing it.

## After the sync

Push `desktop` to the fork (`origin` in CI).
The sync workflow then dispatches `desktop-release.yml`, which compares `version` in `products/desktop/package.json` against the existing `desktop-v<version>` release tag and, when the version changed, builds and publishes a new signed macOS DMG and Windows installer as a GitHub release on the fork.
Bumping that version field is therefore the release trigger.
