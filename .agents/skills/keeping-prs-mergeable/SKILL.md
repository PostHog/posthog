---
name: keeping-prs-mergeable
description: >-
  Sweep a set of open PostHog PRs and drive each toward a mergeable state — CI green, approved,
  and every valid review comment addressed — then report which are ready and babysit any the user
  enqueues. Use when asked to "keep my PRs green", "check my PRs and tell me which to merge", run a
  merge-readiness sweep, keep a batch of PRs current against master, or resolve the conflicts and
  review findings standing between a PR and merge. Covers the readiness bar (bot vs human comments,
  stale bot risk-scores), the per-PR fix loop (re-merge master, resolve conflicts, fix findings,
  preflight, push), the merge boundary (never enqueue without explicit per-PR approval), and running
  the sweep on a cadence. Trigger terms - keep PRs green, merge-readiness, which to merge, keep my
  work green, PR sweep, get PRs mergeable.
---

# Keeping PRs mergeable

Drive a batch of open PRs to mergeable and keep them there. A PR is **mergeable** when three things
hold together, not one:

1. **Approved** — `reviewDecision == APPROVED` (a human approval that satisfies the branch rule).
2. **CI green** — no failing required checks.
3. **Review comments addressed** — every _valid_ open comment is fixed or consciously dispositioned.

Green alone is not mergeable. A PR can be green and still carry an unaddressed P1 in a review thread.
Report a PR as ready only when all three hold.

## The merge boundary (do not cross it)

Agents must **never enqueue or merge** a PR without explicit user approval in the current
conversation for that specific PR. Preparing, fixing, and reporting "ready" is the job; landing it
is the user's call. See [merging-prs](../merging-prs/SKILL.md).

In practice the `/trunk merge` comment is also blocked by the auto-mode permission classifier, so you
usually **cannot** post it yourself even after approval. When a PR is ready, surface the command for
the user to run instead of trying to work around the block:

```sh
! gh pr comment <number> --body "/trunk merge"
```

Never post other comments on a PR on the user's behalf (house rule) — no status pings, no "noop".

## The sweep

Poll each PR and classify it. One compact pass:

```sh
for pr in <numbers>; do
  gh pr view $pr --json number,state,isDraft,reviewDecision,mergeStateStatus,statusCheckRollup \
    --jq '"#\(.number) \(if .isDraft then "draft" else "ready" end) rev=\(.reviewDecision//"-") merge=\(.mergeStateStatus) fail=\([.statusCheckRollup[]|select(.conclusion=="FAILURE")]|length) pend=\([.statusCheckRollup[]|select((.conclusion==null) and (.status!="COMPLETED"))]|length)"'
done
```

Read the columns:

- `merge=BLOCKED` with `rev=APPROVED` and `fail=0` usually means **ready, awaiting enqueue** — not a
  problem. `BLOCKED` is the normal resting state for an approved PR that hasn't been queued.
- `merge=DIRTY` means **conflicting with master** — needs a re-merge (see below).
- `merge=UNKNOWN` across many PRs at once means **master just advanced** and GitHub is recomputing
  mergeability — transient, re-check next pass rather than acting.
- `merge=UNSTABLE` means a non-required check failed — look, but it may not block.
- A single lingering `pend` is often a check that never fires for this diff (e.g. a visual-review
  playwright job on a backend-only PR). The Trunk queue runs required CI on its own merge branch, so
  such a check does not block a merge. Confirm which check it is before treating `pend` as "not ready":
  `gh pr view <n> --json statusCheckRollup --jq '.statusCheckRollup[]|select((.conclusion==null) and (.status!="COMPLETED"))|(.name//.context)'`

## Judging review comments

`fail=0` is not the whole bar. Pull the open review threads and judge each:

```sh
gh api graphql -f query='{repository(owner:"PostHog",name:"posthog"){pullRequest(number:<n>){reviewThreads(first:100){nodes{isResolved isOutdated path comments(first:5){nodes{author{login} body}}}}}}}'
```

- **Unresolved ≠ unaddressed.** A thread only "unresolved" because nobody clicked Resolve, on a PR a
  human approved, is dispositioned. Read the content.
- **Bot reviewers** (greptile, veria-ai, chatgpt-codex-connector, graphite-app) post advisory
  findings. Judge them on merit: a P1 data-correctness or security finding is real and worth fixing;
  a style nit the human approver left alone is not a blocker.
- **A bot risk score is a snapshot, not a live gate.** Check the comment's timestamp against the PR's
  latest commit — a "5/10, 2 open" badge dated before your fix push is **stale**; the bot may not
  re-run promptly. Report the substance (findings fixed in code + green CI), and say the badge is
  lagging rather than treating it as a fresh rejection.
- **Fix vs disposition.** Fix a valid finding, or state why it's intentional (the author may have a
  documented rationale in a comment or docstring — e.g. an approximate cap that is deliberately
  coarse). Don't invent changes where the author already decided against them.

## The per-PR fix loop

For a PR that is not yet ready:

1. **Re-merge master first.** These branches drift fast; a stale base produces phantom failures.
   `git merge origin/master --no-edit`. Resolve conflicts:
   - **Generated files** (`schema.py`/`schema_enums.py`, `frontend/**/generated/api.*`,
     `services/mcp/**/generated*`, `frontend/src/taxonomy/core-filter-definitions-by-group.json`):
     don't hand-merge. Regenerate from source (`hogli build:schema`, `bin/build-taxonomy-json.py`),
     or take master's version and let the `tests-posthog[bot]` regenerate on push — it auto-commits
     "chore: update OpenAPI generated types". Confirm the source of truth (serializer / `tools.yaml` /
     `schema-general.ts`) carries the change so the regen re-adds it.
   - **Source conflicts**: usually a union merge (both sides added an entry to the same list, enum,
     import block, or registry). Keep both, deduplicate identical additions, and verify order matters
     (a method that continues a class must stay attached to it).
2. **Fix the real failures / findings.** Invoke the mandatory skill for the area first —
   [improving-drf-endpoints](../improving-drf-endpoints/SKILL.md) (viewsets/serializers),
   [writing-tests](../writing-tests/SKILL.md), [writing-ui-components](../writing-ui-components/SKILL.md),
   [writing-code-comments](../writing-code-comments/SKILL.md). Read the failing job's log to classify
   real vs flaky vs stale-base ([debugging-ci-failures](../debugging-ci-failures/SKILL.md)).
3. **Verify locally, scoped to the change.** Run `uv run pytest <file>` — the flox `.venv` can lack
   `time_machine`, and `uv run` resolves the right environment. A ClickHouse/DB test errors on a
   migration mismatch until master is merged in (it seeds the prewarmed DB); merge master, then run.
4. **Preflight and push.** `hogli ci:preflight --fix` catches deterministic CI breakage; the pre-push
   hook runs it `--strict`. Never `--no-verify`. Push per-PR; don't batch unrelated fixes.

## Gotchas

- **Worktrees.** A branch already checked out under `.claude/worktrees/` cannot be checked out again
  in the main tree (`git checkout` errors "already checked out"). Operate in that worktree instead.
  Check `git worktree list` first. The `&&` in `checkout && reset` short-circuits on a failed
  checkout — run them separately so a merge never lands on the wrong branch.
- **Restore the shared checkout.** If the main working tree belongs to another session, switch it back
  to its branch when done.
- **The queue publishes no check run here.** Trunk merge progress is not on the PR's checks. Read it
  from `trunk merge status <n>` or the `trunk-io[bot]` sticky comment. Babysit per
  [merging-prs](../merging-prs/SKILL.md); classify a kick per
  [triaging-merge-queue-failures](../triaging-merge-queue-failures/SKILL.md).
- **Sequence PRs that share files.** When two PRs touch the same files, merging one conflicts the
  other. Merge one, then re-merge master into the sibling and re-flag it. Let the user pick the order
  when it's a product decision (e.g. a base behavior that a dependent PR should sit on top of).

## Running it on a cadence

To keep watching without being asked each time, run this as a self-paced loop
([loop](../../../.claude/skills/loop/SKILL.md) / a `ScheduleWakeup` cadence). Each tick: re-poll,
report only what changed (mark quiet ticks as noop), flag any PR that became ready, and report any
queue outcome. Match the interval to what you're waiting on — minutes while CI or the queue is
active, tens of minutes when the set is static. Stop escalating the interval past ~1h.

## Report shape

Group by state so the user can act at a glance: **ready to enqueue now** (with the `/trunk merge`
command), **parked** (and behind what), **failing / open findings** (with the specific blocker), and
**merged**. Keep it scannable.
