---
name: ship-it-factory
description: >
  Ships one large change as many small PRs that stamphog can auto-approve, then
  queues them. Measures the change with the real stamphog gate code (size
  limits from .stamphog/policy.yml and AGENT_APPROVALS.md, plus the deny list),
  splits the files into groups that fit, opens one PR per group, marks them
  ready for review, waits for green CI, adds the stamphog label, and comments
  /trunk merge on each approved PR after one user confirmation. Works in
  PostHog Desktop (git_signed_commit, gh_stack) and in a local terminal. Use
  when asked to "ship it factory", split a change into stamphog-sized PRs,
  break up a PR that is too large for auto-review, or ship a change as many PRs.
---

# ship-it-factory

Ship one large change as many small PRs that stamphog can approve.
The flow: freeze the change in one source commit, measure it, split it into groups that fit, open a PR per group, mark them ready, wait for green CI, add the `stamphog` label, then comment `/trunk merge` on each approved PR.

`scripts/stamphog_budget.py` is the only helper. It runs the stamphog engine from this repo, so it is the source of truth for the limit, the files that do not count, and the deny categories. Do not restate those rules from memory.

## Hard rules

- Do not post `/trunk merge` before the user says "yes" to the final PR list in this conversation (step 6). AGENTS.md requires explicit approval for each PR or stack that can land.
- Do not use `--no-verify`, `gh pr merge`, or a force-push on a PR that is in the merge queue.
- Each PR must build and pass its tests on its own base. Do not cut a coherent change into PRs that are only green together.
- Do not label a PR whose group has a deny category. Stamphog refuses it. Send it to a human reviewer.
- In PostHog Desktop, `git commit` and `git push` are blocked. Use the `git_signed_commit` tool and the `gh_stack` tool. Do not use the `gh stack` CLI.

## Step 1: Freeze the change in one source commit

Every later step reads from one ref, `refs/ship-it-factory/source`. It is local and never pushed.

```bash
git fetch origin master
# A shallow clone (common in PostHog Desktop) has no merge base until it has more history.
[ "$(git rev-parse --is-shallow-repository)" = true ] && git fetch --deepen=50 origin master
# The branch has commits: put them on the current master. Stash dirty work around the rebase.
git rebase origin/master
# The tree has uncommitted work: save all of it (new files too) in one stash commit.
git add -A && git stash push -m ship-it-factory
SOURCE=$(git rev-parse 'stash@{0}')   # or: SOURCE=$(git rev-parse HEAD) when the tree was clean
git update-ref refs/ship-it-factory/source "$SOURCE"
```

The rebase matters: files restored from an older base would revert newer `master` changes.

## Step 2: Measure and plan

```bash
uv run .agents/skills/ship-it-factory/scripts/stamphog_budget.py --source refs/ship-it-factory/source --verbose
```

`--verbose` lists each file as `counts` or `exempt`. The JSON line shows the substantive size, the roofs (the global limit, or a higher one from an `AGENT_APPROVALS.md` grant), and the deny categories. Tell the user the limit and the size.

When `ok` is true, make one PR. Otherwise group the files. Each group is one PR:

- Target about 85% of the limit, to leave space for review fixes.
- Keep each test file with the code that it tests, and generated files with the source change that makes them.
- Put both paths of a renamed file in the same group. `--verbose` does not list the old path, but the plan check does.
- Give deny-category files their own group. That PR needs a human review.
- Order the groups so each one builds on the base plus the groups before it: shared types and helpers, models, API and logic, frontend, then the wiring that turns the feature on.
- Prefer independent PRs off `master`. Stack only when a group needs code from an earlier group.
- When one file alone is over the limit, stop and ask the user: refactor it first, or send that PR to a human.

Write the groups to `/tmp/ship-it-factory/plan.json` in merge order, as `{"<slug>": ["path", ...]}`, then check:

```bash
uv run .agents/skills/ship-it-factory/scripts/stamphog_budget.py --source refs/ship-it-factory/source --plan /tmp/ship-it-factory/plan.json
```

`ok: true` means every group fits, every changed path is in exactly one group, no rename is split, and no group has a deny category. A deny-category group can stay, marked "human review". Show the user the plan as a table, then continue.

## Step 3: Open the PRs

For each group, in plan order:

```bash
git switch --detach origin/master          # independent PR; for a stack, stay on the branch below
git restore --source=refs/ship-it-factory/source --staged --worktree -- <files>
```

`git restore` adds, changes, and deletes the files to match the source, and stages them.
Run the fast checks for those files (`ruff`, `hogli test <tests>`, the frontend type check), and fix problems inside the group.

Commit on a new branch and open a draft PR:

- PostHog Desktop: call `git_signed_commit` with `branch: "posthog/<slug>"`. The checkout moves to that branch.
- Local terminal: `git switch -c <slug>`, `git commit`, `git push -u origin HEAD`.

```bash
gh pr create --draft --base master --head <branch> --title "<type>(<scope>): <summary>" --body-file -
```

For a stack, `--base` is the branch below. Use the repository PR template and `writing-pr-descriptions`. Add a "Part N of M" line that links the other PRs. After the last PR, link a stack bottom to top with the `gh_stack` tool (`operation: "create"`).

## Step 4: Mark ready, wait for green CI, label

Stamphog does not review drafts. Mark each PR ready with `gh pr ready <n>`.

Poll the required checks, a few minutes apart. Do not block on one long sleep.

```bash
gh pr checks <n> --required > /dev/null; echo "<n> $?"    # 0 pass, 1 fail, 8 pending
```

- Fail: read the failure (`debugging-ci-failures`), fix it on that branch, and commit again. A cancelled run also fails: rerun it as `merging-prs` describes.
- A flake or a red `master`: tell the user, and stop for that PR.
- Pass: `gh pr edit <n> --add-label stamphog`. When the label route is not available, use the PostHog MCP tool `stamphog-review-runs-create`.

## Step 5: Wait for the stamphog verdict

```bash
gh pr view <n> --json reviewDecision,labels --jq '[.reviewDecision, ([.labels[].name] | index("stamphog") != null)]'
```

- `APPROVED`: the PR is ready.
- Label gone and no approval: stamphog refused, escalated, or gated the PR. Read its reason, fix the concrete issue, commit, and add the label again. When the reason is size or a deny category, split the group again or send it to a human.

  ```bash
  gh api "repos/{owner}/{repo}/pulls/<n>/reviews" --jq '[.[] | select(.user.login == "stamphog[bot]")] | last | .body'
  ```

- Label still there and no verdict: the review is pending or retrying. A new push starts a new review.

## Step 6: Confirm, then comment /trunk merge

List the approved PRs with links and ask: "Comment /trunk merge on these N PRs?". Wait for "yes".

```bash
gh pr comment <n> --body "/trunk merge"
```

Comment on each independent PR in plan order. For a stack, comment on the top PR only: the queue merges every layer below it with it. To watch the queue or handle a kick, use `merging-prs`. Re-enqueue a failed PR at most once, and only with approval.

## Step 7: Report and clean up

Give the user one table: PR link, size, CI, stamphog verdict, queue state. Name each PR that needs a human, and why.
When every PR has merged, delete the source ref with `git update-ref -d refs/ship-it-factory/source`.

## Related skills

- `merging-prs`: watch a PR through the Trunk merge queue and handle a kick.
- `stacking-prs`: restack or land a stack.
- `writing-pr-descriptions`: write each PR body.
- `debugging-ci-failures`: find why a required check is red.
