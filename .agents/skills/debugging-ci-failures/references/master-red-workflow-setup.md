# Setting up the master-red diagnosis workflow

The agent that answers a master-red incident is a PostHog Workflow, built in the UI, with a Slack-message trigger and one "Create AI task" step.
Its instructions point at `master-red-incident.md` in this directory, so what the agent does ships by PR while the wiring stays configuration.

Nothing in this repository fires it. The DevEx alerter posts its incident message to #alerts-devex as it always has, and the workflow triggers on that message.

## Why this shape

- A CI failure is not a webhook a workflow can subscribe to, and `ALLOWED_GITHUB_TRIGGER_EVENTS` covers only issues, comments, PRs and pushes. The alert message is the only artifact that means "master has been red long enough to matter".
- The alerter already decides that. It opens an incident on a 5-run failure streak or 60 minutes red, so triggering on its message inherits that judgment instead of re-deriving it.
- A Slack-triggered task binds to the thread automatically, so the answer lands under the alert rather than in a new message.

## Build it

In [Workflows](https://us.posthog.com/project/2/workflows), create a workflow with:

**Trigger: Slack message posted**

| Field                         | Value                           | Why                                                                                      |
| ----------------------------- | ------------------------------- | ---------------------------------------------------------------------------------------- |
| Channel                       | `#alerts-devex`                 | Required. Without it the trigger runs on every message in every channel the bot is in.   |
| Who can start a run           | Specific apps, `A0B83REAZU3`    | The DevEx app, which posts the incident.                                                 |
| Ignore replies inside threads | on                              | The agent's own replies land in this channel. Without this they re-trigger the workflow. |
| Additional filter             | `text` contains `Master is red` | The same app posts other alerts, and each one would otherwise start a run.               |

Edits do not fire the trigger: `_TRIGGERING_SUBTYPES` in `slack_workflow_events.py` admits only real posts, so the alerter's per-tick update of its own message is ignored.

**Step: Create AI task**

| Input                     | Value                                                                                                                                                                             |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Instructions              | The alert text as data, then: read `.agents/skills/debugging-ci-failures/references/master-red-incident.md` and its parent `SKILL.md`, and answer the incident as they prescribe. |
| Repository                | `PostHog/posthog`                                                                                                                                                                 |
| Model                     | empty, so the default applies                                                                                                                                                     |
| Connectors                | none                                                                                                                                                                              |
| PostHog MCP scopes        | `read_only`                                                                                                                                                                       |
| Max parallel tasks        | 1                                                                                                                                                                                 |
| Reply in the Slack thread | on                                                                                                                                                                                |

Notes on the choices:

- Connectors stay empty because the Slack reply is native. The step binds `slack_context` from the triggering message, and replies in that thread reach the agent, so no MCP installation is involved.
- `read_only` covers the engineering analytics reads the parent skill uses. The run needs no write scope anywhere.
- One parallel task keeps a burst of incidents from fanning out into a burst of runs.
- The task runs as the workflow's owner. That account must stay active in the org.

## The contract with the alerter

The `text` filter matches a string built by `buildAnchorMessage` in `.github/scripts/ci-alerts-devex.js`.
Reword that headline and the workflow silently stops firing, with no error anywhere.
Change one and check the other.

## Turning it off

Disable the workflow. The alerter is unaffected, because it does not know the workflow exists.

## Letting it open PRs later

The step has no PR switch: a task opens a PR only when its instructions ask for one, and `master-red-incident.md` forbids it.
Leave that in place until the thread answers have been read for a few weeks.
When the cause is infrastructure, no PR is the correct output, and an agent that opens one produces noise with a review cost attached.
