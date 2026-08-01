---
name: merging-prs
description: Merge a PR into main through the Trunk merge queue and babysit it until it lands. Enqueue with a "/trunk merge" comment, then poll the "Trunk Merge Queue" check run and the PR state until it is MERGED or FAILED, reporting the Trunk bot's failure reason if the PR is kicked out. Use when asked to merge a PR, "merge when ready", "land it", "ship it", or to babysit/watch a PR through the queue. Never use `gh pr merge` in this repo -- the queue is the only path into main.
allowed-tools: Bash(gh pr view:*), Bash(gh pr checks:*), Bash(gh pr comment:*), Bash(gh pr ready:*), Bash(gh api:*), Bash(sleep:*)
---

# Merge a PR through the Trunk merge queue

Merges into `main` go **exclusively** through the [Trunk](https://trunk.io) merge
queue. `gh pr merge` and the GitHub merge button are blocked by branch ruleset.
To merge, you enqueue the PR with a comment, then watch it until Trunk lands it.

When a developer says "merge this PR", "merge it when it's ready", "land it",
"ship it", or "babysit this PR", do the full loop below — enqueue **and** watch
to completion, reporting the outcome.

`<n>` below is the PR number. Resolve the repo slug once if you need it:
`REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)`.

## 1. Preflight

```bash
gh pr view <n> --json state,isDraft,mergeable,reviewDecision,statusCheckRollup
```

- **Not open** (already merged/closed) → report and stop.
- **Draft** → it can't be merged. Ask the developer to confirm, then
  `gh pr ready <n>` before continuing. Don't un-draft silently.
- **Failing required checks** (`statusCheckRollup`) → the queue will just reject
  it. Report which checks are red and stop; fix them first. **Pending** checks
  are fine — the queue waits for them.
- **Not yet approved** (`reviewDecision` empty or `REVIEW_REQUIRED`) → fine,
  enqueue anyway. See below.
- **Merge conflicts** (`mergeable == "CONFLICTING"`) → report and stop; rebase first.

Enqueueing before approval is safe, and is the closest thing this repo has to
auto-merge. A submitted PR sits in Trunk's `Queued` state until GitHub's branch
protection on `main` is satisfied — one approving review, code-owner review, and
the required checks (`build`, `quality`, `unit-test`, `integration-test`,
`typecheck`) — and Trunk merges it once they land. Trunk is not a bypass actor on
those rules, so it cannot merge an unapproved or red PR.

The catch: **pushing new commits drops the PR from the queue.** If review
feedback is likely, either wait for approval before enqueueing, or re-enqueue
with `/trunk merge` after each push.

## 2. Enqueue

```bash
gh pr comment <n> --body "/trunk merge"
```

Within ~2 minutes, confirm Trunk picked it up — a check run whose name starts
with `Trunk Merge Queue` should appear on the head commit:

```bash
SHA=$(gh pr view <n> --json headRefOid -q .headRefOid)
gh api repos/$REPO/commits/$SHA/check-runs \
  --jq '.check_runs[] | select(.name | startswith("Trunk Merge Queue")) | {name, status, conclusion, details_url}'
```

If nothing appears after a couple of minutes, the developer may lack write
access or GitHub-comment commands may be disabled — report that and suggest the
`trunk-merge-queue-submit` label as a fallback.

## 3. Poll until it lands

Loop about every 60 seconds, up to ~45–60 minutes total. Each iteration:

```bash
gh pr view <n> --json state,mergedAt          # MERGED  -> success, stop
SHA=$(gh pr view <n> --json headRefOid -q .headRefOid)
gh api repos/$REPO/commits/$SHA/check-runs \
  --jq '.check_runs[] | select(.name | startswith("Trunk Merge Queue")) | {status, conclusion, details_url}'
sleep 60
```

- `state == "MERGED"` → done. Report success with the merge commit.
- Check run `status` moves `queued` → `in_progress` → `completed`. Report each
  transition so the developer can follow along.
- Watch the **check run + PR state**, not `gh pr checks --watch`: the queue runs
  CI on Trunk's own draft/`trunk-merge/**` branch, so this PR's own checks don't
  reflect the queue's testing.
- If it's parked in `Queued` waiting on a human review, say so once and slow the
  cadence to ~5 minutes. Keep watching — the merge still has to be reported.
- Stop at the timeout with a status summary rather than looping forever. If it
  was still waiting on review, say that's why and offer to keep watching.

## 4. Handle failure

If the check run completes with `conclusion == "failure"` (or the PR drops out
of the queue), Trunk kicks the PR and its bot comments with the failing
workflow. Read the newest comments and report the reason:

```bash
gh pr view <n> --comments | tail -n 40
```

- If the failure is clearly caused by this PR **and** the fix is obvious, fix it,
  push, wait for the PR's own checks to go green, and re-enqueue **once** with
  `/trunk merge`.
- Otherwise stop and report the failure and the workflow link. Don't repeatedly
  re-enqueue a red PR.

## 5. Cancel

If the developer asks to stop the merge:

```bash
gh pr comment <n> --body "/trunk cancel"
```

Confirm the check run reports cancelled.

## Hard rules

- **Never** run `gh pr merge` — it's blocked and it's not how this repo merges.
- **Never** force-push a branch while it is in the queue — it removes the PR
  from the queue.
- Re-enqueue a failed PR **at most once** automatically; beyond that, hand back
  to the developer.
