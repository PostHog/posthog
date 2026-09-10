# Setting up the master-red diagnosis workflow

The agent that answers a master-red incident is a PostHog Workflow with a webhook trigger and one "Create AI task" step.
The DevEx alerter opens the Slack incident, then invokes the workflow with the incident thread and observed CI state.
The task instructions point to `master-red-incident.md` in this directory, so investigation behavior ships through the repository while the workflow owns task creation and Slack delivery.

## Why this shape

- The alerter already decides when a sustained failure deserves an incident. The workflow should not derive that decision again.
- A direct webhook avoids matching Slack message text and starts only when the alerter opens an incident.
- The payload carries the Slack channel and thread timestamp, so the task can reply to the existing incident.
- The payload also carries the observed failing lanes. The agent verifies them against GitHub before diagnosing because the lane can recover after the alert opens.

## Build it

Create a workflow with a POST webhook trigger.
Emit `$slack_message_received` so the task action can use the existing Slack-thread integration.
Map these request values into event properties without changing their shape:

| Event property         | Request value                                  |
| ---------------------- | ---------------------------------------------- |
| `channel`              | `request.body.properties.channel`              |
| `ts`                   | `request.body.properties.ts`                   |
| `workflows`            | `request.body.properties.workflows`            |
| `since`                | `request.body.properties.since`                |
| `commit_streak`        | `request.body.properties.commit_streak`        |
| `latest_commit_sha`    | `request.body.properties.latest_commit_sha`    |
| `all_failing_runs_url` | `request.body.properties.all_failing_runs_url` |

Configure the "Create AI task" step with:

| Input                     | Value                                                                                                                                                                               |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Instructions              | The alert fields as data, then: read `.agents/skills/debugging-ci-failures/references/master-red-incident.md` and its parent `SKILL.md`, and answer the incident as they prescribe. |
| Repository                | `PostHog/posthog`                                                                                                                                                                   |
| Model                     | `gpt-5.6-sol`                                                                                                                                                                       |
| Connectors                | none                                                                                                                                                                                |
| PostHog MCP scopes        | `read_only`                                                                                                                                                                         |
| Max parallel tasks        | 1                                                                                                                                                                                   |
| Reply in the Slack thread | on                                                                                                                                                                                  |

The editor hides the Slack-thread option for webhook triggers, but the action defaults it to on.
Preserve that default so the emitted Slack event binds the task to the incident thread.

Keep the task prompt below the incident data explicit:

```text
Begin with tool calls. Read .agents/skills/debugging-ci-failures/references/master-red-incident.md and its parent SKILL.md in this repository, then answer this incident exactly as they prescribe. Emit no plan, preamble, or progress update. Post one reply: the verdict, the failing job, the evidence, and the next action for a human. Never re-run or dispatch CI, and never push a commit or open a PR.
```

## Contract with the alerter

`.github/scripts/ci-alerts-devex.js` sends `properties.workflows` as lane records.
Each record contains the displayed name, workflow file, trigger event, observed run ID and URL, creation time, and head SHA.
Keep the workflow's `workflows` property mapping unchanged so these records reach the task.
Older events can contain names only, and `master-red-incident.md` retains that fallback.

The workflow must preserve `channel` and `ts` because the task uses them to reply in the incident thread.
The alerter invokes the workflow only when it creates an incident, so an unchanged open incident does not start another task.

## Turning it off

Disable the workflow or remove the alerter's diagnosis webhook configuration.
The Slack incident continues to work without the diagnosis task.

## Letting it open PRs later

The task opens a PR only when its instructions ask for one, and `master-red-incident.md` forbids it.
Keep that rule until the workflow has enough reviewed history to justify write access.
Infrastructure failures need no code change, and speculative repair PRs create review work without resolving the incident.
