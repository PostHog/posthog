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
```

List who wrote the commits. GitHub credits an author only when the commit email is linked to their account, and an empty `login` means it is not:

```sh
gh pr view <n> --json commits --jq '.commits[].authors[] | {login, email}'
```

When one person wrote every commit (merges from master aside), squash.
Use their linked email, or else the PR author's no-reply address:

```sh
gh api users/<login> --jq '"\(.id)+\(.login)@users.noreply.github.com"'
git merge --squash <sha>
git commit --author="<name> <email>"
```

When several people wrote commits, cherry-pick, so each author keeps credit:

```sh
git cherry-pick --no-merges "$(git merge-base origin/master <sha>)..<sha>"
```

An empty commit, such as one pushed only to rerun CI, stops the cherry-pick. Drop it with `git cherry-pick --skip`.

A conflict can mean that master already has part of the change, from another PR or an earlier re-creation.
Search master for it before you resolve the conflict, and stop if the fork PR is no longer needed.

Both paths keep the contributor as author and make you the committer.
Every branch here requires signed commits, so contributor commits cannot be pushed as they are.
Your commits carry your signature when `commit.gpgsign` is on.

## 3. Compare before the first push

A push to this repository cannot be taken back, so check the branch first.
Run this before you add your own commits:

```sh
{
  git diff --name-only --no-renames -z "$(git merge-base origin/master <sha>)" <sha>
  git diff --name-only --no-renames -z origin/master HEAD
} | xargs -0 git diff <sha> HEAD --
```

No output means the branch matches the reviewed code in every file that the fork PR or the new branch changes.
Each remaining hunk is a master change made after the fork branched, or a conflict resolution, or a fix the contributor made inside a merge commit that `--no-merges` dropped.
Read each hunk and know which kind it is.

Then add your own fixes as separate commits, so the history shows which part is theirs.

## 4. Open the new PR

Write the body with `/writing-pr-descriptions` and the repo template. Then add:

- In Problem: "Contributed by @<login> in #<n>, which cannot merge because backend CI does not run for fork PRs."
- Anywhere in the body, this hidden marker, exactly: `<!-- fork-pr: <n> @<login> -->`. It is not a leftover template comment, so keep it through later body edits.
- The `Closes #<issue>` line from the fork PR.
- Screenshots linked from the fork PR, not uploaded again.
- In Agent context: cherry-picked or squashed, and which commits are your follow-ups.

Do not add a `Co-authored-by` trailer.
The merge queue squash-merges, and GitHub adds a `Co-authored-by` line for every commit author other than the PR author.

When the new PR merges, the `Thank fork contributor` job in `.github/workflows/pr-closed.yml` reads the marker.
It comments on the fork PR with a link to the merged PR, then closes the fork PR.
Leave the fork PR open until then.
