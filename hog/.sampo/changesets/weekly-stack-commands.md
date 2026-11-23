---
npm/hog: minor
---

Manage PostHog definitions in your repository with hog init, check, diff, push and pull. Get the diff as a pull request comment from a keyless GitHub Actions job, then push from the default branch after the merge.

Use `hog stack secret set`, `list` and `remove` to manage the secrets your definitions reference by name.

`hog ci setup --stack` writes a workflow that comments the diff on pull requests from the same repository. It installs hog before the pull request's code and needs a committed package-lock.json in the stack folder. It never pushes: a person runs `hog push` after the merge.

Changes to existing commands: `hog ci setup` now stops when HOG_DRY_RUN is set, instead of asking PostHog for an approval. `hog setup` and `hog init` stop when AGENTS.md or CLAUDE.md holds repeated or unpaired PostHog setup markers. `hog check` sends no usage event and skips the update check.

`hog stack generate` writes a typed Python, Go or TypeScript module of the events a stack defines, and `--check` catches a stale one in CI. `hog stack context-pages enable` and `disable` let an organization admin allow a stack to manage context pages.

A write that PostHog refuses because a stack manages the entity now names the definition's file to edit, in every command.

After a push with an unknown outcome, `hog diff` shows which entities the push may have created without recording them, and a person accepts them with `hog stack reconcile --diff <id>` before the stack pushes again.

`hog stack adopt <kind> <key> <entity-id>` binds an existing entity to a definition already in the folder, and `hog diff` suggests it after an interrupted push. `hog push --max-removals` now asks a person at a terminal to confirm what the push removes and recreates, and refuses agents and scripts.
