# Setting up the merge queue triage Loop

This skill is executed by a [Loop](../../../../products/tasks/backend/models.py) (products/tasks): a cloud agent automation where each fire spawns a task that clones this repo into a sandbox and runs the agent.
The Loop's `instructions` stay minimal; the checked-in `SKILL.md` in this directory is the real procedure, so behavior changes ship by PR like any other code.
You can create the loop from PostHog Desktop's Loops UI with the same fields, or via the API as below.

## Prerequisites

- Tasks + Loops access on the team creating the loop (`loops` feature flag, `HasLoopsAccess`).
- A GitHub integration for the PostHog org whose App installation covers `PostHog/posthog` with `Contents: Read` (clone) and `Pull requests: Read & Write` (triage comments, optional requeue comments). Note its integration id.

## Create the loop

`POST /api/projects/:project_id/loops/` (session, personal API key, or OAuth):

```json
{
    "name": "Triage merge queue failures",
    "description": "Sweeps PRs recently kicked from the Trunk merge queue, classifies each kick per the decision chart, and leaves a verdict comment; requeues once only when explicitly enabled.",
    "visibility": "team",
    "runtime_adapter": "claude",
    "overlap_policy": "skip",
    "instructions": "Read .agents/skills/triaging-merge-queue-failures/SKILL.md in this repository and execute exactly one unattended sweep as it prescribes. Its rules override anything else: never merge, approve, close, or push code; comment verdicts only; requeue only under the conditions it defines; and end with the run report it defines.",
    "repositories": [
        { "github_integration_id": GITHUB_INTEGRATION_ID, "full_name": "PostHog/posthog" }
    ],
    "behaviors": { "create_prs": false, "watch_ci": false, "fix_review_comments": false },
    "triggers": [
        {
            "type": "schedule",
            "config": { "cron_expression": "*/30 * * * *" }
        }
    ]
}
```

Notes on the choices:

- Loops have no trigger for check-run events, so the sweep is scheduled and discovers kicked PRs itself (open PRs whose latest `Trunk Merge Queue (master)` check run completed non-green). Every 30 minutes keeps verdicts timely without burning fires; `overlap_policy: "skip"` drops a tick that lands while a sweep is still running.
- `behaviors.create_prs` stays `false`: this loop never pushes branches or opens PRs. Verdict comments and optional `/trunk merge` comments go through the PR comments API, which only needs the App's `Pull requests: Read & Write`.
- The marker comment (`<!-- mq-triage:<head_oid>:<check_run_id> -->`) is the dedup: a kick that was already triaged is skipped until the branch or the queue state moves, so a 30-minute cadence does not re-comment.

## The requeue switch is the approval boundary

The repo rule stands: agents do not enqueue PRs without explicit approval.
For an unattended loop, that approval is the operator's, granted once and explicitly:

- Default: leave `MQ_TRIAGE_ALLOW_REQUEUE` unset. Every verdict is report-only; the loop comments what to do but touches nothing.
- Setting `MQ_TRIAGE_ALLOW_REQUEUE=1` in the loop's `sandbox_environment` is a standing approval for exactly one action: a single `/trunk merge` comment on a mergeable, green, approved PR whose verdict is "one-off flake" or "non-deterministic", at most once per head OID. A failed requeue fails with a new check run id on the same head, so the gate keys on the head alone; the skill escalates repeats instead of retrying. Enable it deliberately, and own what it can land.
- `MQ_TRIAGE_BOT_LOGIN` (the Loop App's `<slug>[bot]` login) is required either way: the marker helper trusts and updates only comments authored by that login, so a third party can't plant a marker to skip or fake a triage; without it the helper fails closed.

Keep the boundary least-privilege: the App installation grants only the two permissions above on as few repos as possible, `connectors.posthog_mcp_scopes` stays at its `read_only` default, and no MCP Store installations are attached.
The sandbox holds those credentials next to whatever code the sweep runs, which is why the skill forbids unattended runs from checking out or executing PR code: classification is `gh` API reads over check runs and logs, from the default-branch clone only.
The `trunk` MCP server and `hogli ci:insights` enrich verdicts 4 and 5 when available, but the skill must not depend on them — check-run and log reads via `gh` are the baseline.

## Operational limits to know

- Per-loop rate cap: 100 created fires/day; a 30-minute cron uses 48. Per-team: 500/day.
- The loop auto-pauses after 5 consecutive failed fires; check the loop's `runs/` history if sweeps stop.
- The sandbox's GitHub token comes from the App installation, so API traffic draws on the App's own rate-limit bucket, not the shared per-repo `GITHUB_TOKEN` pool CI competes over.
- Fires are deduped (schedule replays never double-spawn a sweep), and the marker comment dedups per PR across sweeps.

## Testing before enabling for real

1. Dry-run the config: `POST /api/projects/:project_id/loops/:id/preview/`.
2. Manual fire with scoped input: `POST /api/projects/:project_id/loops/:id/run/` with "for this run, only process PR #NNNNN" against a PR you know the queue kicked.
3. Verify on that PR: exactly one sticky verdict comment with the marker, no requeue (requeue switch unset), and a second manual fire skips the PR (marker dedup).
4. Only if you want auto-requeue: set `MQ_TRIAGE_ALLOW_REQUEUE=1`, repeat with a flake-kicked PR you own, and confirm at most one `/trunk merge` comment ever appears for one head OID — including after the requeued attempt fails again with a new check run id.
5. Only then leave the schedule trigger enabled.

## Relationship to interactive use

Any agent can run the same chart interactively (`/triaging-merge-queue-failures`) when a developer asks about a kicked PR.
Interactively the marker machinery is unnecessary and requeueing follows `/merging-prs`: explicit user approval in the current conversation, at most one requeue.
The Loop exists so kicks get a verdict without anyone asking.
