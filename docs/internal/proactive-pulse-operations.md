# Proactive Pulse operations

Pulse is disabled by default. Set `PULSE_PROACTIVE_ENABLED=true` before any scheduled subscription can create a Pulse run. The draft PR, experiment draft, and public-research capabilities each require their own explicit enablement flag as well.

Do not enable the master switch during a rolling worker deployment. First wait until every analytics-platform worker runs the release that registers the Pulse workflow and activities. This prevents an older poller from receiving a workflow type it does not know.

`PULSE_TASK_QUEUE` defaults to the analytics-platform queue. To isolate Pulse, move it in two deployments while the master switch remains off:

1. Start workers polling the dedicated queue with `PULSE_TASK_QUEUE=pulse-task-queue`.
2. After those pollers are healthy, set the same value on the analytics workers that dispatch Pulse children.
3. Run the controlled-runtime gate below, then enable `PULSE_PROACTIVE_ENABLED`.

Never point dispatchers at a new queue before its workers are polling.

| Control                             |                       Default | Purpose                                                                        |
| ----------------------------------- | ----------------------------: | ------------------------------------------------------------------------------ |
| `PULSE_MAX_TEAM_CONCURRENT_RUNS`    |                             1 | Active runs per team                                                           |
| `PULSE_MAX_GLOBAL_CONCURRENT_RUNS`  |                            10 | Active runs across the instance                                                |
| `PULSE_MAX_TEAM_DAILY_RUNS`         |                            24 | Daily team budget                                                              |
| `PULSE_MAX_GLOBAL_DAILY_RUNS`       |                           100 | Daily instance budget                                                          |
| `PULSE_WALL_CLOCK_SECONDS`          |                          3600 | Analysis and execution deadline                                                |
| `PULSE_FINALIZATION_MARGIN_SECONDS` |                           300 | Reserved time for cancellation and durable finalization                        |
| `PULSE_MAX_ACTIONS`                 |                             3 | Action proposals retained per run                                              |
| `PULSE_MAX_TOOL_CALLS`              |                            20 | MCP tool-call budget                                                           |
| `PULSE_MAX_PUBLIC_RESEARCH_CALLS`   |                             3 | Public-research budget                                                         |
| `PULSE_MAX_AGENT_CONTEXT_TOKENS`    |                        200000 | Agent input context window (`200000` or `1000000`); this is not a spend budget |
| `PULSE_PUBLIC_REPOSITORY_ALLOWLIST` |                             — | Comma-separated public `owner/repository` names permitted for draft PRs        |
| `PULSE_TASK_QUEUE`                  | analytics-platform-task-queue | Separately routable Pulse workflow landing zone                                |

Use the master flag as the emergency stop. Capability flags should be enabled one at a time after observing bounded runs. Limits are server-owned guardrails; malformed or excessive values are clamped by the Pulse orchestration layer.

Draft PR authorization fails closed for public repositories unless their normalized `owner/repository` name is in `PULSE_PUBLIC_REPOSITORY_ALLOWLIST`. The GitHub repository cache must also explicitly identify a repository as private or public; missing, malformed, or conflicting visibility metadata is denied.

Disabling draft PR consent durably revokes the caller-bound Tasks capability and publication lease in the same database transaction as the subscription change. Worker cancellation runs after commit and is retried by the Pulse reaper.

Branch and draft-PR creation each persist an irreversible-start state before the external request. Revocation prevents later publication stages, but an external request that already crossed that boundary is reconciled to its exact outcome instead of being retried or assumed undone.
