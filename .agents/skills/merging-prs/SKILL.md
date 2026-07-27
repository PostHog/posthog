---
name: merging-prs
description: >
  Merge a PR into `master` through the Trunk merge queue and babysit it until it
  lands. Enqueue with a `/trunk merge` comment, then watch the `Trunk Merge Queue
  (master)` check run and the PR state until it is MERGED or the queue kicks it
  out, reporting the Trunk bot's failure reason. Use when asked to merge a PR,
  "merge when ready", "land it", "ship it", or to babysit/watch a PR through the
  queue. Never use `gh pr merge` in this repo — the queue is the only path into
  master.
---

# Merge a PR through the Trunk merge queue

Merges into `master` go **exclusively** through the [Trunk](https://trunk.io) merge queue.
`gh pr merge` and the GitHub merge button are blocked by branch ruleset.
To merge, you enqueue the PR with a comment, then watch it until Trunk lands it.

`<n>` below is the PR number.
Resolve the repo slug once if you need it: `REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)`.

## 1. Preflight

```bash
gh pr view <n> --json state,isDraft,mergeable,reviewDecision,statusCheckRollup
```

- **Not open** (already merged/closed) → report and stop.
- **Draft** → it can't be merged. Ask the developer to confirm, then `gh pr ready <n>` before continuing. Don't un-draft silently.
- **Failing required checks** (`statusCheckRollup`) → the queue will just reject it. Report which checks are red and stop; fix them first. **Pending** checks are fine — the queue waits for them. To work out _why_ a check is red, use `/debugging-ci-failures`.
- **Merge conflicts** (`mergeable == "CONFLICTING"`) → report and stop; merge `master` in first.

## 2. Enqueue

```bash
gh pr comment <n> --body "/trunk merge"
```

Within ~2 minutes, confirm Trunk picked it up — a check run whose name starts with `Trunk Merge Queue` should appear on the head commit:

```bash
SHA=$(gh pr view <n> --json headRefOid -q .headRefOid)
gh api repos/$REPO/commits/$SHA/check-runs \
  --jq '.check_runs[] | select(.name | startswith("Trunk Merge Queue")) | {name, status, conclusion, details_url}'
```

If nothing appears after a couple of minutes,
the developer may lack write access or GitHub-comment commands may be disabled —
report that and suggest the `trunk-merge-queue-submit` label as a fallback.

## 3. Watch until it lands

Watch the **check run + PR state**, not `gh pr checks --watch`:
the queue runs CI on Trunk's own `trunk-merge/**` branch,
so this PR's own checks don't reflect the queue's testing.

Arm a monitor that emits only on state transitions and exits once the PR reaches a terminal state —
don't burn turns on a foreground poll loop:

```bash
PR=<n>; REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner); prev=""
while true; do
  state=$(gh pr view "$PR" --json state -q .state 2>/dev/null || echo UNKNOWN)
  sha=$(gh pr view "$PR" --json headRefOid -q .headRefOid 2>/dev/null)
  queue=$(gh api "repos/$REPO/commits/$sha/check-runs" \
    --jq '.check_runs[] | select(.name | startswith("Trunk Merge Queue")) | "\(.status)/\(.conclusion // "-")"' 2>/dev/null | head -n1)
  cur="pr=$state queue=${queue:-none}"
  [ "$cur" != "$prev" ] && echo "$cur"
  prev="$cur"
  case "$state" in MERGED|CLOSED) exit 0 ;; esac
  sleep 60
done
```

Run it with the `Monitor` tool (`timeout_ms: 3600000`) so each transition arrives as a notification while you do other work.
Without `Monitor`, run it with `Bash` `run_in_background`.
Never block on a foreground `sleep`.

- `state == "MERGED"` → done. Report success with the merge commit.
- The queue check moves `queued` → `in_progress` → `completed`. Relay each transition so the developer can follow along.
- A queue run can take a while — the full CI fan-out runs on Trunk's branch. Stop at the timeout with a status summary rather than re-arming forever.

## 4. Handle failure

If the check run completes with `conclusion == "failure"` (or the PR drops out of the queue),
Trunk kicks the PR and its bot comments with the failing workflow.
Read the newest comments and report the reason:

```bash
gh pr view <n> --comments | tail -n 40
```

- If the failure is clearly caused by this PR **and** the fix is obvious, fix it, push (the `ci:preflight` pre-push hook must pass — never `--no-verify`), wait for the PR's own checks to go green, and re-enqueue **once** with `/trunk merge`.
- If the failure looks like a flake or an unrelated master breakage, say so and hand back — `/debugging-ci-failures` and `/fixing-flaky-tests` cover the diagnosis; don't re-enqueue on a hunch.
- Otherwise stop and report the failure and the workflow link. Don't repeatedly re-enqueue a red PR.

## 5. Cancel

If the developer asks to stop the merge:

```bash
gh pr comment <n> --body "/trunk cancel"
```

Confirm the check run reports cancelled.

## Hard rules

- **Never** run `gh pr merge` — it's blocked and it's not how this repo merges.
- **Never** force-push a branch while it is in the queue — it removes the PR from the queue. This includes restacking a stacked PR whose base is queued.
- Re-enqueue a failed PR **at most once** automatically; beyond that, hand back to the developer.
