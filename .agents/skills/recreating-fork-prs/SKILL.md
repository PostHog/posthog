---
name: recreating-fork-prs
description: >
  Re-creates a reviewed pull request from a fork on a branch in PostHog/posthog,
  so it can get the required checks and merge, while the contributor stays the
  commit author and GitHub credits them on the squash commit. Use when a fork PR
  fails with "Depot CI does not run fork pull requests", when its
  `Backend CI on Depot / Test results` check stays pending, or when someone asks
  how to merge, land, carry over, or take over a contributor or community PR.
  Not for pull requests opened from a branch in this repository.
---

# Re-creating fork pull requests

Depot CI never runs code from a fork, so a fork PR never gets the required `Backend CI on Depot / Test results` check and cannot merge.
A maintainer re-creates the reviewed change on a branch in this repository.
[Pull requests from forks](../../../docs/published/handbook/engineering/fork-pull-requests.md) has the reasons.

A branch in this repository is trusted: secret-gated CI steps run with its code in control.
Push only the commits you reviewed.
The push and the new PR act in the user's name. Get the user's go-ahead for each one.

```text
- [ ] 1. Pin the fork PR's head SHA, then review it
- [ ] 2. Rebuild the change on a new branch
- [ ] 3. Compare the branch with the reviewed SHA
- [ ] 4. Open the new PR
```

## 1. Pin, then review

```sh
gh pr view <n> --json headRefOid,author,isCrossRepository
```

Review the code at that `headRefOid`.
When the review ends, run the command again.
If `headRefOid` changed, the contributor pushed during the review: review the new commits and pin the new SHA.
Every later step uses the pinned SHA, never the fork's branch name.

## 2. Rebuild the change

GitHub serves fork commits by SHA from this repository:

```sh
git fetch origin master <sha>
git switch -c <branch> origin/master
git cherry-pick --no-merges "$(git merge-base origin/master <sha>)..<sha>"
```

An empty commit, such as one pushed only to rerun CI, stops the cherry-pick. Drop it with `git cherry-pick --skip`.

A conflict can mean that master already has part of the change, from another PR or an earlier re-creation.
Search master for it before you resolve the conflict, and stop if the fork PR is no longer needed.

Cherry-pick keeps each commit's author and makes you the committer.
Every branch here requires signed commits, so contributor commits cannot be pushed as they are.
The cherry-picked commits carry your signature when `commit.gpgsign` is on.

GitHub credits an author only when the commit email is linked to their account.
An empty `login` here means the email is not linked:

```sh
gh pr view <n> --json commits --jq '.commits[].authors[] | {login, email}'
```

Then rewrite the author to their no-reply address before you add any commit of your own:

```sh
gh api users/<login> --jq '"\(.id)+\(.login)@users.noreply.github.com"'
git rebase origin/master --exec 'git commit --amend --no-edit --author="<name> <no-reply address>"'
```

When one person wrote every commit and the history is noisy (many fixups, merges from master), squash it instead:

```sh
git merge --squash <sha>
git commit --author="<name> <linked email or no-reply address>"
```

With several authors, cherry-pick, so each author keeps credit.

## 3. Compare before the first push

A push to this repository cannot be taken back, so check the branch first.
Run this before you add your own commits:

```sh
git diff <sha> HEAD -- $(gh pr view <n> --json files --jq '.files[].path')
```

No output means the branch matches the reviewed code in every file the PR touches.
Each remaining hunk is a master change made after the fork branched, or a conflict resolution, or a fix the contributor made inside a merge commit that `--no-merges` dropped.
Read each hunk and know which kind it is.

Then add your own fixes as separate commits, so the history shows which part is theirs.

## 4. Open the new PR

Write the body with `/writing-pr-descriptions` and the repo template. Then add:

- In Problem, this exact line: "Contributed by @<login> in #<n>, which cannot merge because backend CI does not run for fork PRs."
- The `Closes #<issue>` line from the fork PR.
- Screenshots linked from the fork PR, not uploaded again.
- In Agent context: cherry-picked or squashed, and which commits are your follow-ups.

Do not add a `Co-authored-by` trailer.
The merge queue squash-merges, and GitHub adds a `Co-authored-by` line for every commit author other than the PR author.

When the new PR merges, the `Thank fork contributor` job in `.github/workflows/pr-closed.yml` reads the "Contributed by" line.
It comments on the fork PR with the merged commit and the co-author credit, then closes the fork PR.
Leave the fork PR open until then.
