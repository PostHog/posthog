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

```text
- [ ] 1. Review the fork PR and pin its head SHA
- [ ] 2. Rebuild the change on a new branch
- [ ] 3. Compare the branch with the reviewed SHA
- [ ] 4. Open the new PR
- [ ] 5. Close the fork PR
```

## 1. Review and pin

Review the fork PR on GitHub as it is. Then record the head SHA you reviewed:

```sh
gh pr view <n> --json headRefOid,author,isCrossRepository
```

The contributor can push again at any time.
Every later step uses this SHA, never the fork's branch name.

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

Cherry-pick keeps the contributor as author and makes you the committer.
Every branch here requires signed commits, so contributor commits cannot be pushed as they are.
The cherry-picked commits carry your signature when `commit.gpgsign` is on.

When the fork history is noisy (many fixups, merges from master), squash it into one commit with the contributor as author:

```sh
git merge --squash <sha>
git commit --author="$(git log -1 --format='%an <%ae>' <sha>)"
```

GitHub credits an author only when the commit email is linked to their account.
An empty `login` in `gh pr view <n> --json commits --jq '.commits[].authors[]'` means the email is not linked.
Then use their no-reply address instead:

```sh
gh api users/<login> --jq '"\(.id)+\(.login)@users.noreply.github.com"'
```

Put your own fixes in separate commits after theirs, so the history shows which part is theirs.

## 3. Compare before the first push

A push to this repository cannot be taken back, so check the branch first.
For cherry-picked commits:

```sh
git range-diff "$(git merge-base origin/master <sha>)..<sha>" origin/master..HEAD
```

Each pair must show `=`. A `!` means conflict resolution changed the content: read that change.
A `<` row with no match is a commit you skipped. Confirm that it was empty.
For a squash, compare `git diff "$(git merge-base origin/master <sha>)" <sha>` with `git diff origin/master HEAD`.
Leave your follow-up commits out of this comparison.

## 4. Open the new PR

Write the body with `/writing-pr-descriptions` and the repo template. Then add:

- In Problem: "Contributed by @<login> in #<n>, which cannot merge because backend CI does not run for fork PRs."
- The `Closes #<issue>` line from the fork PR.
- Screenshots linked from the fork PR, not uploaded again.
- In Agent context: cherry-picked or squashed, and which commits are your follow-ups.

Do not add a `Co-authored-by` trailer.
The merge queue squash-merges, and GitHub adds a `Co-authored-by` line for every commit author other than the PR author.

## 5. Close the fork PR

After the new PR exists, tell the contributor on the fork PR where their change went, link the new PR, and close the fork PR.
