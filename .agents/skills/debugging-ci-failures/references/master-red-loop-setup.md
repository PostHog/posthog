# Setting up the master-red diagnosis Loop

This skill is executed by a [Loop](../../../../products/tasks/backend/models.py) (products/tasks): a cloud agent automation whose fire spawns a task that clones this repo into a sandbox and runs the agent.
The Loop's `instructions` stay minimal; the checked-in `SKILL.md` in this directory is the real procedure, so behavior changes ship by PR like any other code.

The fire comes from `.github/scripts/ci-alerts-devex.js`, which calls `loops/:id/trigger/` the moment it opens a master CI incident in #alerts-devex.

## Why an API trigger and not a GitHub one

`ALLOWED_GITHUB_TRIGGER_EVENTS` is `("issues", "issue_comment", "pull_request", "push")`, so a CI failure is not an event a Loop can subscribe to.
A push trigger would also fire on every master push rather than on failure, and its payload carries no Slack thread, so the agent could not answer in the incident thread.
"An incident opened" exists only inside the alerter's reconcile, which is why the alerter fires the Loop itself.

## Prerequisites

- Tasks and Loops access on the team creating the loop (`loops` feature flag, `HasLoopsAccess`).
- A GitHub integration whose App installation covers `PostHog/posthog` with `Contents: Read`. This loop never writes to the repo. Note its integration id.
- A Slack MCP Store installation for the run to post its reply with. Note its installation id.

## Create the loop

`POST /api/projects/2/loops/` (session, personal API key, or OAuth):

```json
{
    "name": "Master-red diagnosis",
    "description": "Diagnoses an open master CI incident and answers in its #alerts-devex thread.",
    "visibility": "team",
    "runtime_adapter": "claude",
    "overlap_policy": "skip",
    "instructions": "Read .agents/skills/debugging-ci-failures/references/master-red-incident-loop.md in this repository, and its parent SKILL.md, then answer exactly one incident as they prescribe. Their rules override anything else: post one reply in the thread from the trigger payload, never re-run or dispatch CI, and never push a commit or open a PR.",
    "repositories": [{ "github_integration_id": GITHUB_INTEGRATION_ID, "full_name": "PostHog/posthog" }],
    "behaviors": { "create_prs": false, "watch_ci": false, "fix_review_comments": false },
    "connectors": { "mcp_installation_ids": ["SLACK_INSTALLATION_ID"], "posthog_mcp_scopes": "read_only" },
    "triggers": [{ "type": "api", "enabled": true }]
}
```

Notes on the choices:

- `triggers` must include an enabled `api` trigger. Without one the endpoint answers `reason: disabled` and never fires.
- `overlap_policy: "skip"` bounds the blast radius of a long outage. Each incident fires once anyway, so this only matters when two incidents open close together.
- `behaviors.create_prs: false` makes this a report-only loop, which is the whole write boundary. The agent reads CI and writes one Slack message.
- `posthog_mcp_scopes: "read_only"` covers the engineering analytics reads that `/debugging-ci-failures` uses. The run needs no write scope.
- The run executes as the loop's owner. Ownership must stay with an active member of the org, or every fire is refused with `owner_inactive`.

## Arm the workflow

Two values, both scoped to project 2:

1. Mint a project secret API key at `us.posthog.com/project/2/settings/environment-secret-api-keys` with the `loop:write` scope. That scope exists for this call: see the comment on `("loop", "write")` in `posthog/scopes.py`. The settings page is gated on the `PROJECT_SECRET_API_KEYS` flag and asks you to reauthenticate.
2. Store the `phs_` value as the repository secret `POSTHOG_DEVEX_LOOP_SECRET_API_KEY`, and set `DIAGNOSIS_LOOP_ID` in `.github/workflows/ci-alerts-devex.yml` to the loop's id.

A project secret API key is project-wide, so a leaked key can fire any loop in project 2. Treat it accordingly.

## Turning it off

Clear `DIAGNOSIS_LOOP_ID`, or disable the loop.
Either way the alerter is unaffected: the fire is best-effort, and the job log records `created=false reason=disabled`.

## Opening fix PRs later

`behaviors.create_prs` is the switch, and loop-origin runs are bot-authored, so a fix PR is never attributed to a person who did not ask for it.
Leave it off until the thread verdicts have been read for a few weeks.
When the cause is infrastructure, no PR is the correct output, and an agent that opens one produces noise with a review cost attached.
