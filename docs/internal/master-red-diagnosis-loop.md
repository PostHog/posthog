# Master-red diagnosis loop

When the DevEx alerter opens a master CI incident in #alerts-devex, it fires a cloud agent that diagnoses the failure and answers in that incident's Slack thread.
The alert stays the product: the fire is best-effort, and a loop that is unconfigured, disabled, rate-capped or unreachable leaves the alert untouched.

## How it is wired

1. `.github/workflows/ci-alerts-devex.yml` reconciles master health after every Backend CI completion on master, and every five minutes as a backstop.
2. When that reconcile **opens** an incident, `.github/scripts/ci-alerts-devex.js` posts the anchor message, then calls `POST /api/projects/2/loops/<id>/trigger/` with the incident as its payload.
3. The trigger creates the run synchronously and dispatches its Temporal workflow on commit, so the sandbox starts within seconds rather than waiting for a poller.
4. The run reads the payload, investigates, and posts its answer into the incident thread over the Slack MCP connector.

The fire happens on open only.
A workflow that goes red later shows up in the agent's own reading of master, and a second run would answer the same thread twice.

## Latency

Time to answer is the incident open plus sandbox boot plus the agent's own turns.
Sandbox boot measured p50 24.8s and p90 38.9s over 255,681 runs in the two weeks to 2026-08-26.

The dominant wait is upstream of all of that: the alerter only opens an incident once a gating workflow has been red for `WORKFLOW_FAILURE_MINUTES_THRESHOLD` (60) minutes or has failed `WORKFLOW_FAILURE_STREAK_THRESHOLD` (5) runs in a row.
Those thresholds exist so transient flakes stay quiet.
Lowering them makes the agent answer sooner and makes the channel noisier, in the same proportion, so treat it as an alerting-policy change rather than a tuning knob for this loop.

## Trigger payload

Rendered into the run's prompt inside a fenced block marked as data, not instructions, so a commit message cannot steer the agent.

```json
{
  "slack": { "channel": "C0AS64N6DJL", "thread_ts": "1787764295.504509" },
  "repository": "PostHog/posthog",
  "since": "2026-08-26T15:23:00Z",
  "failing_workflows": [
    {
      "name": "Backend CI",
      "workflow_file": "ci-backend.yml",
      "run_url": "https://github.com/PostHog/posthog/actions/runs/32988481661",
      "red_for_minutes": 108,
      "consecutive_failures": 5
    }
  ],
  "red_commit_streak": 0,
  "latest_commit": { "sha": "abd151c", "html_url": "...", "message": "...", "author": "..." },
  "all_failing_runs_url": "https://github.com/PostHog/posthog/actions?query=branch%3Amaster+is%3Afailure"
}
```

`Idempotency-Key` is `master-red-<thread_ts>`.
A `LoopFire` dedups on it, so a retried job or a tick that races the same anchor reuses the first run instead of starting a rival one.

## Loop configuration

Create the loop once in the product, in project 2, then put its id in `DIAGNOSIS_LOOP_ID` in the workflow.

| Field                             | Value                 | Why                                                                                                                      |
| --------------------------------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `visibility`                      | `team`                | The run belongs to DevEx, not to whoever created it.                                                                     |
| `repositories`                    | `["PostHog/posthog"]` | The agent needs the repo to read workflows and tests.                                                                    |
| `behaviors.create_prs`            | `false`               | Report-only to start. See "Opening fix PRs" below.                                                                       |
| `overlap_policy`                  | `skip`                | A long outage must not stack up rival runs.                                                                              |
| `connectors.mcp_installation_ids` | Slack                 | How the run answers in the incident thread.                                                                              |
| `connectors.posthog_mcp_scopes`   | read                  | Reads engineering analytics for CI history.                                                                              |
| `skill_bundles`                   | none                  | The sandbox clones this repo, so the run reads `.agents/skills/debugging-ci-failures` directly and cannot drift from it. |

Instructions, kept short because the checked-in skill carries the method:

> Master CI is red. Follow `/debugging-ci-failures` on the runs named in the trigger payload.
> Classify the failure as infrastructure (runner loss, dispatch overflow, cache miss), a flaky test, or a real regression, and name the evidence for that verdict.
> Reply once in the Slack thread from the payload: the verdict, the failing job, the evidence, and the next action for a human.
> Say plainly when the cause is not determinable from the logs. Do not guess.

The run executes as the loop's owner.
The owner must stay an active member of the org, or every fire is refused with `owner_inactive`.

## Opening fix PRs

Loop-origin runs are bot-authored (`USER_AUTHORABLE_ORIGIN_PRODUCTS` covers only `user_created` and `slack`), so a fix PR is never attributed to a person who did not ask for it.

Leave `create_prs` false until the thread answers have been read for a few weeks and the verdicts hold up.
Most master-red incidents are infrastructure, where no PR is the correct output, so an agent that opens one is producing noise with a review cost attached.
When it is turned on, keep the PR a draft and never let it reach the merge queue.

## Arming and disarming

Arming needs two values, both scoped to project 2:

- `DIAGNOSIS_LOOP_ID` in `.github/workflows/ci-alerts-devex.yml`.
- `POSTHOG_DEVEX_LOOP_SECRET_API_KEY`, a project secret API key with the `loop:write` scope, as a repository secret.

Clearing `DIAGNOSIS_LOOP_ID` disarms the fire.
Disabling the loop in the product also works, and shows up in the job log as `created=false reason=disabled`.
