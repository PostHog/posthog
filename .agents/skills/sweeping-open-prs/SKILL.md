---
name: sweeping-open-prs
description: >
  Sweeps the user's open PostHog PRs and unsticks each one — merges approved-and-green
  PRs, classifies red CI, chases missing reviews, forces ship-or-close decisions on
  stale drafts, and deletes local branches already squash-merged. Use for "check my
  PRs", "babysit my PRs", a recurring morning PR sweep, or when PRs sit approved but
  unmerged.
---

# Sweeping open PRs

Approval is not the finish line: approved PRs routinely sit unmerged for days behind red CI shards, stack ordering, or plain inattention — accumulating conflicts and losing stamphog approvals to dismissal on the next push.
This sweep converts every open PR from "waiting" into one explicit action.

## Step 1 — inventory

```bash
gh pr list --repo PostHog/posthog --author @me --state open \
  --json number,title,isDraft,createdAt,reviewDecision,mergeable,labels,headRefName,additions,deletions,statusCheckRollup
```

Include sibling repos the user works in (e.g. charts, cloud infra) when relevant.

## Step 2 — triage every PR into exactly one action

Work oldest-first. For each PR take the FIRST matching row:

| State                                | Action                                                                                                                                                                                                                                                                                      |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Approved + checks green + mergeable  | **Merge now** (or `gh pr merge <n> --auto --squash`). Sitting invites conflicts and stamphog-approval dismissal.                                                                                                                                                                            |
| Approved + red checks                | Classify before touching anything: generated-artifact drift (Validate OpenAPI types, query/MCP snapshots) → regenerate locally per `preflighting-pushes` and push; suspected flake or master break → `debugging-ci-failures` (start with `hogli ci:insights`); real failure → fix it today. |
| Approved + blocked by a downstack PR | Land the stack bottom-up first. If reviewers approved several layers, consider collapsing the remaining layers into one PR.                                                                                                                                                                 |
| No review yet + auto-approvable      | `getting-prs-approved` (gates dry-run, then the `stamphog` label).                                                                                                                                                                                                                          |
| No review yet + gated to humans      | `priority-review` label plus a targeted ask per the `getting-prs-approved` escalation ladder. Re-ping anything quiet for more than a day.                                                                                                                                                   |
| Changes requested                    | Address or rebut every comment today, re-request review, and re-apply the `stamphog` label if it was stripped.                                                                                                                                                                              |
| Merge conflicts                      | Rebase or update the branch now, before the conflict grows.                                                                                                                                                                                                                                 |
| Draft, older than a week             | Decide: promote to ready this week, or close with a one-line comment saying why (superseded, deprioritized, parked — see issue). Old drafts rarely land; closing one recovers attention, and the branch still exists.                                                                       |

## Step 3 — local branch hygiene

Squash-merge makes `git branch --merged` useless. Match local branches against merged PR head refs instead:

```bash
gh pr list --repo PostHog/posthog --author @me --state merged --limit 200 \
  --json headRefName --jq '.[].headRefName' > /tmp/merged-refs.txt
git for-each-ref refs/heads --format='%(refname:short)' | grep -Fxf /tmp/merged-refs.txt
```

Delete those local branches (`git branch -D`) after confirming none is checked out or carries unpushed commits (`git log origin/<branch>..<branch>` is empty).
Flag — don't delete — never-landed branches older than a month; list them for an explicit keep-or-kill decision.

## Step 4 — report

End with a compact table: PR → one-line status → action taken → what's still needed and from whom (a named person or team, not "someone").
Put anything approved for more than a day and still unmerged at the top.
