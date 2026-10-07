---
name: ship-it-factory
description: >
  Ships one large change as many small PRs that stamphog can auto-approve, then
  queues them. Reads the stamphog size limit from .stamphog/policy.yml and
  AGENT_APPROVALS.md, measures the change with the real stamphog gate code,
  splits the files into groups that fit, opens one PR per group, marks them
  ready for review, waits for green CI, adds the stamphog label, and comments
  /trunk merge on each approved PR after one user confirmation. Works in
  PostHog Desktop (git_signed_commit, gh_stack) and in a local terminal. Use
  when asked to "ship it factory", split a change into stamphog-sized PRs,
  break up a PR that is too large for auto-review, or ship a change as many PRs.
---

# ship-it-factory

Ship one large change as many small PRs that stamphog can approve.
The flow is: measure the change against the stamphog size limit, split it to fit, open the PRs, mark them ready, wait for green CI, add the `stamphog` label, then comment `/trunk merge` on each approved PR.

Bundled files:

- `scripts/stamphog_budget.py`: measures the change, or a split plan, against the stamphog size gate and deny list.
- `scripts/extract_group.sh`: brings one PR's files from the backup stash into a clean tree and stages them.
- `scripts/pr_status.sh`: prints one status line per PR (draft, CI, review, label).
- `references/recipes.md`: exact command sequences for PostHog Desktop and for a local terminal.

Run the scripts from the repository root. Keep working files (the plan, PR bodies) in `/tmp/ship-it-factory/`.

## Hard rules

- Do not post `/trunk merge` before the user says "yes" to the final PR list in this conversation (step 8). The repository rules require explicit approval for each PR or stack that can land.
- Do not use `--no-verify`, `gh pr merge`, or a force-push on a PR that is in the merge queue.
- Do not split one coherent change into PRs that fail to build or test alone. Each PR must be green on its own base.
- Do not add the label to a PR that touches a stamphog deny category. Stamphog refuses it. Send it to a human reviewer.
- In PostHog Desktop, `git commit` and `git push` are blocked. Use the `git_signed_commit` tool, `gh pr create`, and the `gh_stack` tool. Do not use the `gh stack` CLI.
- Keep customer data, support tickets, and internal threads out of PR titles, bodies, and commits.

## Step 1: Get the stamphog limit

The limit comes from the repository, not from memory.

1. Read `size_gate` in `.stamphog/policy.yml` (`max_lines`, `max_files`). When the file or section is absent, the hosted default applies: 800 lines and 30 files.
2. Find `AGENT_APPROVALS.md` files above the changed paths. A `stamphog:` frontmatter block can raise `max_lines` or `max_files` for the files under that folder, up to the `overrides` ceiling in `policy.yml` (in PostHog: 1000 lines, 50 files). Example: `products/desktop/` allows 1000 lines.
3. Know what counts. The gate counts substantive lines (additions plus deletions) and substantive files. These files do not count: tests (`test_*.py`, `*_test.py`, `*.test.*`, `*.spec.*`, `tests/` and `__tests__/` folders), docs (`.md`, `.mdx`, `.txt`, `.rst`), snapshots (`.snap`, `.ambr`), images, `.lock` files, and `generated/` artifacts. `pnpm-lock.yaml` and `package-lock.json` do count.
4. Know the deny list. Paths that match a `deny` category in `policy.yml` (auth, secrets, migrations, CI workflows, billing, public API schema, lockfiles, stamphog policy) always go to a human, whatever their size.

Then measure the whole change:

```bash
uv run .agents/skills/ship-it-factory/scripts/stamphog_budget.py --base origin/master --verbose
```

The last line is JSON. In a repository that carries the stamphog engine, the script uses the engine's own gate code, so the numbers and deny categories match the hosted review. Tell the user the limit and the measured size before you split.

## Step 2: Plan the split

When the whole change fits and has no deny category, make one PR and go to step 4.

Otherwise, put the changed files into groups. Each group is one PR.

- Target about 85% of the limit (for example 680 of 800 lines). This leaves space for review fixes.
- Put each test file in the same group as the code that it tests. Tests do not count toward the limit.
- Put generated files (OpenAPI types, schema output) in the same group as the source change that makes them.
- Put files that match a deny category in their own group. That PR needs a human review.
- Order groups so that each group builds on the base plus the groups before it: shared types and helpers, then models and migrations, then API and logic, then frontend, then the wiring that turns the feature on.
- Prefer independent PRs off `master`. Use a stack only when a group needs code from an earlier group that has not merged.
- When one file alone is over the limit, do not split the file across PRs by hand. Tell the user, and ask if they want a refactor first or a human review for that PR.

Write the plan to `/tmp/ship-it-factory/plan.json` as `{"<short-pr-slug>": ["path", ...], ...}` in merge order, then check it:

```bash
uv run .agents/skills/ship-it-factory/scripts/stamphog_budget.py --base origin/master --plan /tmp/ship-it-factory/plan.json
```

`ok: true` means every group fits, no file is missing, and no file is in two groups. Fix the plan until `ok` is true, except for deny-category groups, which you mark as "human review".

Show the plan to the user as a table: PR, files, substantive lines and files, independent or stacked, stamphog or human. Continue without a question unless a group needs a human decision.

## Step 3: Build each PR

Follow `references/recipes.md`, section "Build the PRs". In short:

1. Put the full change on the current `origin/master`, then save it in a backup stash: `git stash push --include-untracked -m ship-it-factory-backup`. Keep the stash until every PR has merged.
2. For each group, in plan order:
   - Go to the base: `git switch --detach origin/master` for an independent PR, or stay on the previous group's branch for a stacked PR.
   - Run `extract_group.sh stash@{0} <files>`.
   - Run the fast checks for these files (lint, type check, the tests for the touched code). Fix problems in this group only.
   - Commit on a new branch: `git_signed_commit` with `branch: posthog/<slug>` in PostHog Desktop, or `git switch -c` plus `git commit` plus `git push -u` locally.
   - Open the PR: `gh pr create --draft --base <master or previous branch>`. Use a conventional-commit title. Fill the repository PR template. Add a line "Part N of M" with links to the other PRs.
3. For a stack, link the PRs bottom to top with the `gh_stack` tool (`operation: "create"`).
4. Confirm that the stash now holds nothing that is not in a PR: compare `git stash show --include-untracked --name-only stash@{0}` with the union of the groups.

## Step 4: Mark ready for review

Stamphog does not review draft PRs. After each PR exists:

```bash
gh pr ready <n>
```

## Step 5: Wait for green CI

```bash
bash .agents/skills/ship-it-factory/scripts/pr_status.sh <n1> <n2> ...
```

Poll every few minutes until every PR shows `ci pass`. Do not block on one long foreground sleep. Use a background loop or short polls.

- `ci fail`: read the failure (use the `debugging-ci-failures` skill in the PostHog repo). Fix it on that PR's branch, then commit again. A cancelled run also shows as fail: rerun it, as `merging-prs` describes.
- `mergeable CONFLICTING`: bring the branch up to date (`git_signed_merge` in PostHog Desktop).
- A failure that is clearly not caused by the PR (a flake or a broken `master`): tell the user, and do not continue for that PR.

## Step 6: Add the stamphog label

When a PR shows `ci pass`, and its group has no deny category:

```bash
gh pr edit <n> --add-label stamphog
```

When the label route is not available, request the review with the PostHog MCP tool `stamphog-review-runs-create` (`repository`, `pr_number`) and poll `stamphog-review-runs-get`.

## Step 7: Wait for the stamphog verdict

Poll `pr_status.sh` until each labeled PR shows `review APPROVED`.

- `APPROVED`, label kept: the PR is ready.
- Label removed and no approval: stamphog refused, escalated, or gated the PR. Read the newest `stamphog[bot]` review on the PR. Fix the concrete issue, push, and add the label again. When the reason is size or a deny category, the plan was wrong: split again or route to a human.
- Label kept, no verdict after a long time (`WAIT` or `ERROR`): the next push retries. Tell the user.
- A new push after approval starts a new review for the new head.

## Step 8: Confirm, then comment /trunk merge

Show the user a list of the approved PRs with links, and ask one question: "Comment /trunk merge on these N PRs?". Wait for "yes".

Then, for each approved PR:

```bash
gh pr comment <n> --body "/trunk merge"
```

- Independent PRs: comment on each PR, in plan order.
- A stack: comment on the top PR only. The queue merges that PR and every unmerged layer below it, together.
- When the `trunk` CLI is installed and logged in, `trunk merge <n>` does the same and reports the result at once.

Confirm that Trunk took each PR: `trunk merge status <n>`, or the `trunk-io[bot]` comment on the PR. To watch a PR through the queue, or to handle a kick, use the `merging-prs` skill. Re-enqueue a failed PR at most once, and only with the user's approval.

## Step 9: Report

Give the user one table: PR link, size, CI, stamphog verdict, queue state. List each PR that needs a human and the reason. Keep the backup stash until every PR has merged, then drop it: `git stash drop stash@{0}` (check the message first).

## Related skills

- `merging-prs`: watch a PR through the Trunk merge queue, and handle a kick.
- `stacking-prs`: create, restack, or land a stack of PRs.
- `writing-pr-descriptions`: write each PR body to the repository template.
- `debugging-ci-failures`: find why a required check is red.
- `triaging-merge-queue-failures`: decide what to do after the queue removes a PR.
