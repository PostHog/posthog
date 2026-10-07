# ship-it-factory recipes

Exact command sequences. `<base>` is `origin/master` (use `origin/main` in a repository whose default branch is `main`).

## Scripts

The scripts are in `.agents/skills/ship-it-factory/scripts/`. Run them from the repository root.
`stamphog_budget.py` declares its dependency (PyYAML) inline, so run it with `uv run`.

## Put the change on the current base

The change can be uncommitted work, commits on a branch, or both.

```bash
git fetch origin master
git branch ship-it-factory-original HEAD          # local safety copy, never pushed
# Commits on the branch: rebase them onto the base, then turn them into staged changes.
git stash push --include-untracked -m ship-it-factory-wip   # only when the tree is dirty
git rebase origin/master                                    # resolve conflicts here, if any
git stash pop                                               # only when you stashed above
git reset --soft origin/master
```

After this, `git diff --cached origin/master` plus the unstaged and untracked files is the full change, and HEAD is `origin/master`.

Measure and check the plan now (before you make the backup stash), because the budget script reads the working tree:

```bash
uv run .agents/skills/ship-it-factory/scripts/stamphog_budget.py --base origin/master --verbose
uv run .agents/skills/ship-it-factory/scripts/stamphog_budget.py --base origin/master --plan /tmp/ship-it-factory/plan.json
```

## Build the PRs

```bash
git stash push --include-untracked -m ship-it-factory-backup
git stash list | head -1     # confirm stash@{0} is ship-it-factory-backup
```

For each group in plan order:

```bash
# Independent PR:
git switch --detach origin/master
# Stacked PR: stay on the branch of the group below.

.agents/skills/ship-it-factory/scripts/extract_group.sh 'stash@{0}' <file> <file> ...

# Fast checks for these files only. In the PostHog repo, for example:
#   ruff check <py files> && ruff format --check <py files>
#   hogli test <test files>
#   pnpm --filter=@posthog/frontend typescript:check   (frontend groups)
```

Commit and open the PR.

PostHog Desktop (cloud run):

1. Call `git_signed_commit` with `branch: "posthog/<slug>"` and a conventional-commit `message`. It commits the staged files and creates the remote branch. The local checkout moves to that branch.
2. Open the PR:

   ```bash
   gh pr create --draft --base master --head posthog/<slug> --title "<type>(<scope>): <summary>" --body-file /tmp/ship-it-factory/<slug>.md
   ```

   For a stacked PR, `--base` is the branch of the group below.

Local terminal:

```bash
git switch -c <user>/<slug>
git commit -m "<type>(<scope>): <summary>"
git push -u origin HEAD      # pre-push hooks run here; fix what they report, never --no-verify
gh pr create --draft --base master --title "<type>(<scope>): <summary>" --body-file /tmp/ship-it-factory/<slug>.md
```

After the last PR:

- Stack in PostHog Desktop: call the `gh_stack` tool with `operation: "create"` and the PR numbers bottom to top.
- Stack in a local terminal: use the `stacking-prs` skill.
- Edit each PR body to add "Part N of M" with links to the others (`gh pr edit <n> --body-file ...`).
- Check that nothing was left out:

  ```bash
  git stash show --include-untracked --name-only 'stash@{0}' | sort > /tmp/ship-it-factory/all.txt
  python3 -c "import json;print('\n'.join(sorted(f for v in json.load(open('/tmp/ship-it-factory/plan.json')).values() for f in v)))" > /tmp/ship-it-factory/planned.txt
  diff /tmp/ship-it-factory/all.txt /tmp/ship-it-factory/planned.txt && echo "all files are in a PR"
  ```

## Fix a PR after it exists

Check out its branch, make the change, then commit again on the same branch:

- PostHog Desktop: `git_signed_commit` (no `branch` argument when you are on the branch). For a stack after a rebase, use `git_signed_rewrite`. To bring in `master`, use `git_signed_merge`.
- Local: `git commit` and `git push`.

A push after stamphog approval starts a new review. Wait for the new verdict before you comment `/trunk merge`.

## Poll status without blocking

```bash
for i in $(seq 1 10); do
  bash .agents/skills/ship-it-factory/scripts/pr_status.sh <n1> <n2> <n3>
  sleep 60
done
```

Keep each tool call under the tool timeout. Repeat the call until every PR shows `ci pass`, then `review APPROVED`.

## Ready, label, merge

```bash
for n in <n1> <n2> <n3>; do gh pr ready "$n"; done
# after ci pass, for PRs without a deny category:
for n in <n1> <n2> <n3>; do gh pr edit "$n" --add-label stamphog; done
# read why stamphog did not approve:
gh api "repos/$(gh repo view --json nameWithOwner -q .nameWithOwner)/pulls/<n>/reviews" \
  --jq '[.[] | select(.user.login == "stamphog[bot]")] | last | .body'
# after the user says yes, for each approved independent PR (or the top of a stack):
gh pr comment <n> --body "/trunk merge"
```
