# Self-optimising workflows

An agent suggests a change to a workflow, a person approves it, and it reaches anyone only through the normal publish.

- **What a customer sees**: [Workflow suggestions](https://posthog.com/docs/workflows/suggestions) (PostHog/posthog.com#19863, draft until the rollout starts).
- **Design**: the internal RFC [requests-for-comments-internal#1108](https://github.com/PostHog/requests-for-comments-internal/pull/1108).
- **Progress**: [#92154](https://github.com/PostHog/posthog/issues/92154).

This page is the operational half: how to turn it on, what it costs us, and what to query. Anything a customer needs belongs in the public page above.

Everything below is behind the `self-optimising-workflows` feature flag, and off per workflow until someone turns it on.

## The loop

1. A workflow owner turns on **Suggest improvements** on a workflow. That writes one `HogFlowOptimisation` row, which is the producer's work list.
2. `signals-scout-workflows` wakes on the Signals schedule, reads the opted-in workflows (`GET /hog_flows?optimisation_enabled=true`), and reads each email step's metrics for the current version (`GET /hog_flows/<id>/metrics/totals?version=<n>`).
3. Where a step underperforms and the change is concrete, the scout calls `workflows-suggest`, which writes a `WorkflowProposal`. It files a report in the Signals inbox pointing at the workflow.
4. The workflow page shows the suggestion with its evidence. A person approves or rejects it.
5. Approving stages the suggestion as the workflow's draft. Publishing that draft is what ships it, and marks the suggestion applied against the version it went live as.
6. The workflow page then shows what the change did: the target metric and its counter-metrics for the version before and the version after.

Nothing an agent does reaches a person's inbox on its own. There is no tool to approve a suggestion, deliberately.

## Turning it on

- The flag `self-optimising-workflows` gates the whole surface. Without it every proposal endpoint 404s and the panel never mounts.
- Per workflow: the switch on the workflow page, or `POST /api/projects/<team>/hog_flows/<id>/optimisation {"enabled": true}`.
- Turning it off keeps the row and stops production. Suggestions already made stay readable and resolvable, because someone still has them to resolve.
- Who turned it on or off is in the workflow's activity log, under History.

## What it costs, and who pays

Today the customer is charged nothing for this, and that is worth being explicit about because the words "AI credits" appear elsewhere in Signals.

- **Signals bills on outcomes, not on LLM spend.** The only chargeable moment in Signals is a report whose implementation task opens a pull request: a flat 1500 credits ($15), once. See `products/signals/backend/billing.py`.
- **A workflow suggestion ships no pull request**, so it never reaches that chargeable moment. The inference a scout run spends is PostHog's cost.
- **The cost scales with opted-in workflows, not with the project.** A project with forty workflows and three opted in pays for three, which is why the opt-in is per workflow rather than per project.
- Whether this should be billed, and how, is open question 3 in the RFC. Until that is decided, do not tell customers this consumes their credits — it does not.

The per-run cost controls, all cheap checks before any model call:

| Control                                                 | Where                                                |
| ------------------------------------------------------- | ---------------------------------------------------- |
| Only opted-in workflows are read                        | `optimisation_enabled=true` on the list              |
| A workflow with a suggestion already waiting is skipped | the scout's orient step                              |
| A step under 20 tracked sends is skipped                | `MIN_EVIDENCE_SAMPLE`, and the scout's disqualifiers |
| One suggestion per workflow per run                     | the scout body                                       |
| Cadence                                                 | the scout's `SignalScoutConfig.run_interval_minutes` |

## Watching it

- **Suggestions**: `workflows_workflowproposal` — status, `created_via`, `source_type`, and `applied_version` for the ones that shipped.
- **Opt-ins**: `workflows_hogflowoptimisation` — `enabled` and `last_run_at`. "Tried it and turned it off" is `enabled = false`.
- **Scout runs**: the Signals run rows for `signals-scout-workflows`, plus its scratchpad entries for what it ruled out.
- **Product analytics**: `hog_flow_optimisation_enabled` / `_disabled`, `hog_flow_proposal_approved` / `_rejected`.

## Known gaps

- `email_unsubscribed` has no producer, so unsubscribe rate is reported as unavailable rather than as zero.
- Engagement metrics split by version only for sends made after the versioned tracking code shipped (#91487). Older versions read `n=0`, which the sample floor labels.
- The outcome card compares two windows, not two arms. Deciding a winner is the RFC's V1a A/B step.
