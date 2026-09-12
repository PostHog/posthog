# Alert investigation agent on the shared agent runtime

Status: proposal. Owner: alerts. Touches: `posthog/temporal/ai/anomaly_investigation/`, `posthog/temporal/alerts/`, `products/alerts/`, `products/signals/backend/scout_harness/`, `products/tasks/backend/facade/`.

## Summary

The alert investigation agent is a hand-rolled, single-pass LangChain tool loop that runs inside a Temporal worker process.
It has five bespoke tools, a hard cap of ten tool calls, no memory between firings, and its own report-parsing and model-quirk workarounds.
Every other agentic surface in the repo (scouts, signal report research, custom signal agents, loops) now runs on the tasks sandbox runtime through `CustomPromptSandboxContext` and `MultiTurnSession`.

This document proposes moving the investigation onto that runtime.
The recommendation is to run it as an **event-triggered system scout**: a canonical `signals-scout-alert-investigation` skill executed by the scout harness, dispatched by the alert check workflow instead of the coordinator, hidden from the scout roster, with the alerts product keeping ownership of the trigger, the per-episode budget, the verdict write-back, and notification gating.

Three options are laid out below. The recommended one is staged so the first two phases are useful on their own even if the third is never taken.

## What exists today

### The investigation agent

Trigger chain (all Temporal, no Celery):

1. `CheckAlertWorkflow` evaluates the alert. Inside the `evaluate_alert` transaction, `decide_investigation` and `claim_investigation_slot` decide whether this check gets an investigation and whether the notification is held (`posthog/temporal/alerts/activities.py`, `posthog/temporal/alerts/investigation.py`).
2. The check workflow starts an abandoned child workflow `anomaly-investigation-{alert_check_id}` on `max-ai-task-queue` (`posthog/temporal/alerts/workflows.py`).
3. `AnomalyInvestigationWorkflow` is one activity, `investigate_anomaly_activity`, with a 40 minute start-to-close timeout and two attempts (`posthog/temporal/ai/anomaly_investigation/workflow.py`).
4. A `run-investigation-safety-net` schedule runs every minute and releases held notifications when an investigation stalls (`posthog/tasks/alerts/investigation_notifications.py`).

Eligibility: `investigation_agent_enabled` on the alert, a `detector_config` (anomaly alerts only), check state FIRING, at most three investigations per firing episode, plus a cooldown lease keyed on the alert.

The agent itself (`runner.py`, `tools.py`, `prompts.py`, `report.py`):

| Aspect     | Today                                                                                                                                              |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Harness    | While-loop over LangChain messages using `MaxChatAnthropic`. Not LangGraph, not the agent server.                                                  |
| Model      | `claude-sonnet-5`, fixed in code.                                                                                                                  |
| Tools      | `run_hogql_query`, `top_breakdowns`, `recent_events`, `fetch_metric_series`, `simulate_detector`, plus the terminal `submit_investigation_report`. |
| Budget     | 10 tool calls, 12k characters per tool result, 180 s per request.                                                                                  |
| Context    | Metric definition, event provenance, a matplotlib chart of the series with anomaly points.                                                         |
| Memory     | None. Each firing starts cold. `previous_verdict` on the episode is the only carry-over.                                                           |
| Output     | `InvestigationReport` (verdict, metric meaning, summary, hypotheses, recommendations).                                                             |
| Robustness | A salvage ladder (`_normalize_report_args`, `_close_truncated_json`, `salvage_report`) for mangled tool-call arguments.                            |

Outputs the rest of the system depends on:

- `AlertCheck.investigation_status`, `investigation_verdict`, `investigation_summary`, `investigation_notebook`, `investigation_error`.
- A notebook rendered from the report with a live embed of the source insight (`notebook.py`).
- Notification gating: true positive notifies, false positive suppresses and stamps `notification_suppressed_by_agent`, inconclusive follows `investigation_inconclusive_action`. A verdict flip later in the episode sends one follow-up.
- A signal into the inbox: `source_product=analytics`, `source_type=anomaly_investigation`, keyed on the episode's first check, with `AnalyticsAnomalyInvestigationSignalExtra` and a dedicated inbox card.
- Slack destination templates read `investigation_notebook_url` and `insight_chart_url`.
- Alert history UI: `InvestigationCell` in `AlertHistorySection.tsx`.

A second, unrelated "investigation" exists for metrics alerts (`posthog/tasks/alerts/metrics_investigation.py`). It has no LLM. It runs bounded ClickHouse queries synchronously and writes only a summary. It is out of scope here and should stay as it is.

### The tasks runtime

`products/tasks` is the shared sandboxed agent runtime. The pieces that matter here:

- `Task` and `TaskRun`, with `Task.origin_product` as the attribution and routing key. Headless origins (`signals_scout`, `scout_suggestions`, `support_reply`, `review_hog`, ...) are reserved server-side and routed to their own OAuth posture and gateway product.
- `products/tasks/backend/facade/agents.py` re-exports `CustomPromptSandboxContext`, `MultiTurnSession`, `create_task_and_trigger`, `poll_for_turn`, `extract_json_from_text`. Its docstring calls this "shared behavioral infrastructure that other products (signals, conversations, evals) build agentic flows on".
- `CustomPromptSandboxContext` carries team, acting user, optional repository, sandbox environment, PostHog MCP scopes, model and runtime adapter overrides, reasoning effort, permission mode, sandbox resources and timeout, `github_read_access`, and `interaction_origin`.
- Hidden runs already exist three ways: `Task.internal=True` (excluded from the default list), origin-based exclusions in `visibility.py` and the activity feed, and the reserved origins the create serializer refuses from API callers. Scout runs are tasks that no one browses in the tasks UI.
- `Task.json_schema` (`output_schema` on `create_and_run`) is a structured, non-PR deliverable the agent runtime enforces at the end of a run. `TaskRun.output["final_message"]` is the free-text one.
- A new origin needs an OAuth app choice in `posthog/temporal/oauth.py`, a gateway product in `_ORIGIN_TO_GATEWAY_PRODUCT` and `MINTABLE_PRODUCTS` in `ai_gateway_token.py`, and an inactivity timeout in `temporal/constants.py` (background origins default to 30 minutes).
- Loops are named, scheduled or event-triggered agent automations. They are user-facing and repository-shaped, so they are not the right container for a per-alert investigation.

### Scouts

A scout is an `LLMSkill` named `signals-scout-*`, seeded per team from `products/signals/skills/`, plus a `SignalScoutConfig` row (schedule, enabled, model, write scopes, `structured_output_schema`, `emit`) and `SignalScoutRun` rows bridged to `TaskRun`.
`scout_harness/runner.py` builds the prompt and toolset, spawns the sandbox through `MultiTurnSession`, pumps the loop to completion or the 15 minute cap, and finalizes the run.

What a scout run gets for free:

- **Tools**: the PostHog MCP tool families with read-only scopes, the `scout-*` tools (scratchpad search and write, runs list, notes list, project profile), the inbox tools, and optionally `emit_report` / `edit_report`. The scope posture in `posthog/temporal/oauth.py` already carries `notebook:write` on every scout and lists `alert:write` among the grantable per-scout write scopes.
- **Memory**: a per-team scratchpad with a key vocabulary (`dedupe:`, `noise:`, `addressed:`, `report:`, `reviewer:`), and the run history of prior runs of the same skill.
- **Steering**: humans leave notes addressed to a skill. Dismissals and reviewer edits on reports are forwarded back as notes.
- **Three output channels**: weak signals into the grouping pipeline, direct reports (`emit_report`), and schema-validated structured output that lands as `$scout_structured_output` events in the team's own project, so a `verdict` field is chartable and alertable without an export step.
- **Governance**: model and runtime routing per team via the `signals-pipeline-models` flag payload, fleet gates, daily run budgets, single-flight per `(team, skill)`, a failure-streak breaker, run cost accounting, evals under `products/signals/eval/`.
- **Dispatch**: three ways a run starts. The coordinator tick, the manual `run` endpoint (with a one-off `run_note` rendered into the prompt), and a workflow "Run scout" step (a pure kick that wakes the step on completion through `emit_workflow_step_resume`). There is no per-event payload channel: `workflow_runs.py` says outright that no content from the triggering event reaches the run.
- **Close-out**: the harness asks for a pydantic `SignalScoutRunSummary` as the final turn, with a text fallback, and returns it in `RunResult`. The activity never retries (`maximum_attempts=1`); the next tick is the retry.
- **Hidden-but-real precedent**: the scout suggestions runner (`suggestions_runner.py`) uses the same harness plumbing under the reserved `scout_suggestions` origin with its own coordinator, hidden from the task tracker. `withheld_skills` hides a scout across the whole config API, but it also stops it being seeded or dispatched, so it is a rollout gate rather than a system-scout posture.

Two existing scouts overlap the alert domain and are worth keeping distinct:

- `signals-scout-insight-alerts` is a daily digest of firings a human likely missed. It explicitly says it does not re-detect and treats `notification_suppressed_by_agent` as a possible false negative to double-check. It is the safety net for the investigation agent, not a replacement.
- `signals-scout-anomaly-detection` watches viewed insights for anomalies using `alert-simulate`. It covers insights without alerts.

`CustomSignalAgent` (`products/signals/backend/custom_agent/`) is an SDK for one-off, event-triggered agents that produce a READY inbox report on the same runtime. Its plan notes no production pilot and no automated tests yet.

## Why move

- **Capability.** The sandbox agent gets the whole PostHog tool surface (trends, funnels, SQL, error tracking, logs, session recordings, feature flags, experiments, annotations), skills such as `investigate-metric` and `investigating-metric-anomalies`, and optionally read-only `gh` for release correlation. The current agent can only run HogQL and look at its own series.
- **Memory and steering.** Alerts flap. The agent should remember that alert 123 dips every Sunday, that the team already acknowledged the checkout regression, and that a human said "ignore staging traffic". Scouts have this; the current agent cannot.
- **Less bespoke code.** `runner.py`, `tools.py`, and the report salvage layer exist to reimplement what the agent server, MCP tools, and structured output already do. The Sonnet 5 tool-call quirks are handled once in the agent server rather than again here.
- **Model routing and cost.** Per-team model and runtime overrides, cost accounting, and LLM analytics attribution already exist for sandbox runs.
- **One agent story.** Users already meet scouts in the inbox. An investigation that reads and writes the same scratchpad, honors the same notes, and files the same kind of report is one coherent product rather than two.

## Options

### Option A: a task with a custom prompt, owned end to end by alerts

Replace the body of `investigate_anomaly_activity` with a `CustomPromptSandboxContext` plus `MultiTurnSession` run, the way `report_generation/research.py` does for signal reports.
Add a reserved `Task.OriginProduct.ALERT_INVESTIGATION`, keep it out of the tasks UI through the visibility lists, grant read-only PostHog MCP scopes, ship the methodology as a bundled skill, and ask for the final answer as JSON matching `InvestigationReport`.
Everything downstream (verdict write-back, notebook, gating, signal) stays as it is.

Pros:

- Smallest conceptual change. The alerts product keeps the whole contract.
- No dependency on scout fleet semantics. No coordinator, no daily budget, no roster.
- `Task.internal=True` hides it, `output_schema` gives a typed return, and `MultiTurnSession.start(model=InvestigationReport)` already parses the final turn into the existing report schema. The verdict comes back synchronously to the calling activity.
- Straightforward to shadow-run against the current agent.

Cons:

- No scratchpad, notes, runs-list, or report channel. Those tools require a `SignalScoutRun` and the `signal_scout_internal:write` scope. Memory would have to be rebuilt or skipped.
- A fourth prompt scaffold to maintain (ground rules, linking rules, evidence bar) next to the scout harness prompt, the research prompt, and the custom agent preamble.
- A new origin with its own OAuth app choice, gateway product, mintable-token entry, and inactivity timeout to wire.

### Option B: a hidden, event-triggered system scout (recommended)

Author `signals-scout-alert-investigation` as a canonical scout skill.
Add a fourth dispatch source, `triggered_by="alert"`, next to schedule, manual, and workflow.
The alert check workflow dispatches a run with a typed trigger context (alert id, check id, episode first check id, previous verdict) instead of the coordinator picking it up on a schedule.
The run uses the ordinary scout harness: the scratchpad keyed per alert, notes, the report channel for true positives, and `structured_output_schema` set to the verdict schema so every investigation also records a chartable `verdict` event.
The close-out model for this lane is `InvestigationReport` rather than the generic run summary, so the typed verdict comes back in `RunResult`.
On completion, the run wakes the alert side (the same completion hook the workflow step uses, carrying the report), which writes the verdict onto the `AlertCheck` and releases or suppresses the notification exactly as today.

The scout is a **system scout**: seeded with no schedule, excluded from the roster and the "Suggested for this project" batch, not counted against `MAX_ENABLED_SCOUTS_PER_TEAM`, not subject to the inactivity sweep or the schedule-only failure breaker, and dispatched only by the alerts product.
Users never enable it directly. Turning on `investigation_agent_enabled` on an alert is the opt-in.

Pros:

- Reuses the whole harness. Prompt scaffold, tools, memory, notes, report channel with charts, structured output, model routing, cost accounting, evals.
- The agent learns per alert across firings and can be steered by a note on the alert.
- Verdict data becomes chartable per team: false-positive rate per alert, verdict trend, time to verdict.
- True positives can become proper inbox reports with charts rather than a weak signal that the grouping pipeline may or may not cluster correctly. The current code already documents that one signal per episode is "a strong default and not a guarantee".
- The insight-alerts digest scout and the investigation scout share the scratchpad vocabulary, so the digest can read `noise:` entries the investigation wrote.

Cons and what they cost:

- Scout dispatch is single-flight per `(team, skill)`. Two alerts firing at once on one team must not queue behind each other. The alert lane needs its own workflow id namespace keyed on `(team, skill, alert)` and a single-flight check scoped the same way.
- Fleet gates (enrollment kill switch, per-team daily run budget, quota pause) were sized for scheduled patrols. An investigation the user explicitly opted into should not be silently dropped by a daily budget. The alert lane needs its own budget (the existing three-per-episode cap plus the cooldown lease) and should bypass the fleet daily budget while still honoring the org-level AI data processing consent and the quota pause.
- The 15 minute runtime cap is shorter than the current 40 minute activity ceiling. In practice the current agent is bounded to about 12 requests at 180 s each, so 15 minutes is comparable, and the safety net already handles a stall. Confirm with p95 run times before cutover.
- Sandbox spin-up adds around a minute of latency before the first tool call. Acceptable for a gated notification; the safety net grace is already 5 minutes after DONE and 90 minutes otherwise.
- Scout runs execute under the signals OAuth app and require `organization.is_ai_data_processing_approved`. Today's agent has no such gate. This has to be surfaced in the alert settings UI as a precondition, or the investigation silently never runs for unapproved orgs.
- `run_note` today is free text from a human, framed in the prompt as untrusted advisory input. The alert trigger context is machine-generated and needs a typed section in the prompt and a typed input on the workflow, not a string smuggled through `run_note`. This is the affordance the workflow "Run scout" step explicitly declined to build; building it here also fixes that step.
- The scout activity never retries. The alert lane relies on the safety net for stalls, and the alert side must treat a `failed` resume as FAILED on the check, the way the current activity's exception path does.

### Option C: a `CustomSignalAgent`

Subclass `CustomSignalAgent` with `identifier() = ("alerts", "anomaly_investigation")`, `NO_REPO` or the team's repository, and `send()` calls with `InvestigationReport` as the output model.
The Temporal wrapper and persistence are provided.

Pros:

- Closest match to the current contract. The pydantic report schema survives unchanged.
- Least new infrastructure.

Cons:

- Always produces a READY `SignalReport`. False positives and inconclusive verdicts should not become inbox items.
- No scratchpad, notes, or structured output. Same memory gap as Option A.
- The launcher is fire-and-forget with no completion hook back to the caller, so the verdict write-back and notification gating would need a new path.
- No production pilot and no tests yet. The investigation would be its first customer and would inherit that risk.

### Comparison

|                                             | A: custom-prompt task  | B: system scout              | C: custom signal agent |
| ------------------------------------------- | ---------------------- | ---------------------------- | ---------------------- |
| Full PostHog tool surface                   | yes                    | yes                          | yes                    |
| Skills                                      | bundled                | canonical, per-team forkable | bundled                |
| Memory across firings                       | build it               | scratchpad                   | build it               |
| Human steering                              | build it               | notes                        | none                   |
| Verdict as data                             | build it               | structured output events     | none                   |
| True positives as inbox reports with charts | via signal             | `emit_report`                | always a report        |
| Completion hook for gating                  | build it               | workflow step resume exists  | build it               |
| Concurrency model                           | per task               | needs per-alert lane         | per task               |
| New origin / OAuth posture                  | yes                    | no (`signals_scout`)         | no                     |
| Fleet gate interplay                        | none                   | needs an alert lane          | partial                |
| Production maturity                         | proven (research flow) | proven (fleet)               | unproven               |

## Recommendation

Take Option B, staged so that each phase ships value and the next phase is a decision, not a commitment.

The reasoning: the thing the current agent lacks most is not a sandbox, it is memory, steering, and a richer tool surface. Only the scout harness provides all three today. Option A gets the sandbox and tools but leaves memory and steering as new work that would end up duplicating the scout scratchpad. Option C is the right shape but is not ready to carry a notification-gating path.

The honest cost of B is that the harness has to grow an event lane: typed trigger input, a pluggable close-out model, per-entity single-flight, and a system posture that skips fleet scheduling and gating. None of that exists today. It is a few hundred lines in `scout_harness/` and `temporal/agentic/`, and the workflow "Run scout" step and any future event-triggered scout benefit from the same lane.

If the signals team does not want the harness to carry an event lane, fall back to Option A. Phase 2 and Phase 3 below are the same under either option; only Phase 0 and the memory parts of Phase 1 differ.

The alerts product stays the owner of the parts that make this an alert feature rather than a patrol: when to run, how many times per episode, what the verdict means for notifications, and how it shows on the alert page. The scout harness owns how the agent runs. `signals-scout-insight-alerts` stays as it is: it audits the investigation's suppressions once a day, which is the right shape for a watchdog and the wrong shape for the investigation itself.

## Phased plan

### Phase 0: make the harness dispatchable off-fleet

Goal: a caller outside the coordinator can start a scout run with typed context and get a completion callback, without touching fleet scheduling.

- Add `TRIGGERED_BY_ALERT` to `scout_harness/limits.py` and `RunSignalsScoutInput`.
- Add a typed `trigger_context` to `RunSignalsScoutInput` and `arun_signals_scout`, rendered by a new prompt section in `scout_harness/prompt.py`. `run_note` stays for humans. Start with a small frozen dataclass: `alert_id`, `alert_check_id`, `episode_first_check_id`, `previous_verdict`, `fired_at`, `insight_short_id`. Carry the metric definition, event provenance, and the detector chart the current activity precomputes as pre-fetched context in the same section, so the agent does not spend its first turns rediscovering them.
- Make the close-out model pluggable per lane. The default stays `SignalScoutRunSummary`; the alert lane passes `InvestigationReport`, and `RunResult` carries the parsed model so the resume payload can include it.
- Add a workflow id builder for the alert lane keyed on `(team, skill, alert_id)` in `scout_scheduler.py`, and scope `_has_running_run` and `_self_heal_stale_runs` by an optional lane key stored in run `metadata`.
- Add a "system scout" posture to `SignalScoutConfig`: seeded with `enabled=False` and no schedule, flagged so `config_registry`, the inactivity sweep, the failure-streak breaker, the roster, and the suggestions batch skip it. A boolean column or a `dispatch_mode` choice; choose the one `/django-migrations` prefers.
- Expose a facade function on `products/signals/backend/facade/api.py`, `start_alert_investigation_run(team_id, skill_name, trigger_context, origin_key) -> handle`, that applies consent and quota-pause gates but not the daily run budget, and dispatches on the signals task queue.
- Reuse `emit_workflow_step_resume` for completion. The alerts side registers an `origin_key` and consumes the resume with the run id, status, and the parsed report. Alternatively the alert check workflow starts the scout run as a child workflow and awaits it, which keeps the verdict write-back in one Temporal history. Pick the child-workflow shape if the resume path cannot carry the report payload.

Tests: dispatch with a trigger context renders the section; two alerts on one team run concurrently; a system scout never appears in the coordinator plan, the roster serializer, or the suggestions batch.

### Phase 1: the skill

Goal: a `signals-scout-alert-investigation` skill that reproduces today's verdict quality with the richer toolset.

- Write `products/signals/skills/signals-scout-alert-investigation/SKILL.md` from the methodology in `prompts.py` (ground the metric, corroborate with a second data stream, magnitude check, verdict rubric) and the `investigate-metric` skill's playbooks. Mark it as a system scout in frontmatter so `lazy_seed` seeds it with the system posture.
- Tools: `alert-get`, `alert-simulate`, `insight-get`, `insight-query`, `query-trends`, `execute-sql`, `annotations-list`, `feature-flag-get-all`, `experiment-get-all`, `query-error-tracking-issues-list`, `query-logs`, `query-session-recordings-list`, plus `emit_report` and `edit_report`. `github_read_access=True` when the team has a GitHub integration, for release correlation.
- Memory vocabulary keyed on the alert id: `pattern:alert:{alert_id}:seasonality`, `noise:alert:{alert_id}`, `addressed:alert:{alert_id}`, `report:alert:{alert_id}`, `verdict:alert:{alert_id}:{episode_first_check_id}`.
- Close-out: the run ends with an `InvestigationReport` (verdict, metric meaning, summary, hypotheses, recommendations). This is the typed return the alert side branches on.
- `structured_output_schema`: one record per run with `verdict`, `alert_id`, `alert_check_id`, `episode_first_check_id`, `confidence`. This is the analytics side-channel, not the return path, and it lands as `$scout_structured_output` events in the team's project.
- Report channel: author or edit a report only for true positives, one per episode, keyed through `report:alert:{alert_id}`. Attach the insight as a chart with pinned dates covering the firing. False positives and inconclusive verdicts write scratchpad entries, not reports.
- Notebook: keep the notebook for now. The alert side renders it from the structured record, so `notebook.py` becomes a pure function of the record. Decide in Phase 3 whether the inbox report replaces it.
- Evals: add cases under `products/signals/eval/` from the existing `test_anomaly_investigation_*` fixtures. The graded property is verdict agreement and whether the summary cites the alerted metric correctly.

### Phase 2: alerts integration and shadow run

Goal: the alert check workflow can run either agent, and the new one is compared against the old one in production before it decides anything.

- Behind a team flag `alert-investigation-sandbox`, `investigate_anomaly_activity` dispatches through the new facade instead of `run_investigation`. In shadow mode it runs both and records both verdicts in `AlertCheck.investigation_error` or a side table, with the old verdict still gating notifications.
- The resume handler writes `investigation_status`, `investigation_verdict`, `investigation_summary`, and the notebook, then calls `_deliver_investigation_outcome` and the signal emission as today. Keep the signal until Phase 3 so the inbox card keeps working.
- Add the `is_ai_data_processing_approved` precondition to the `investigation_agent_enabled` validator and to `InvestigationAgentSettings.tsx` with a link to the consent setting.
- The safety net keeps working unchanged because it reads `AlertCheck` state, not the agent.
- Metrics: verdict agreement rate, time to verdict, run cost, timeout rate by cause (the harness already splits `TurnPollTimeout` diagnostics).

Exit criteria: agreement on true positives at or above the current agent on the eval set, p95 time to verdict under the safety net grace, no regression in suppressed-notification complaints.

### Phase 3: cutover and cleanup

- Flip the flag to 100 percent, then delete `runner.py`, `tools.py`, `report.py`, `charts.py`, and the LangChain-specific tests. Keep `metric_definition.py` and `event_provenance.py` only if the skill still wants them as pre-computed context; otherwise fold their queries into the skill as SQL the agent runs itself.
- Decide the inbox story. Either keep emitting the `analytics/anomaly_investigation` signal (weak signal, pipeline groups it) or switch to the report channel (agent-authored report, one per episode) and retire the signal source and card. The report channel is the better fit for a verdict a human should act on; the signal is the better fit if the team wants the grouping pipeline to merge it with other evidence. Recommend the report channel and a `/announcing-behavior-changes` check on the inbox card removal.
- Alert page: link the run transcript from `InvestigationCell`, and add a "Leave a note for the investigation agent" entry that writes a scout note addressed to the skill with the alert id in the body.
- Verdict analytics: a saved insight template over `$scout_structured_output` filtered to the skill, breakdown by `verdict`, per alert.

## Contracts that must not change

- `AlertCheck.investigation_*` fields and their serializer.
- Notification gating semantics, including the inconclusive action and the one verdict-flip follow-up per check.
- The safety net grace periods and its reliance on `AlertCheck` state alone.
- Three investigations per episode and the cooldown lease.
- The `analytics/anomaly_investigation` signal shape until the inbox decision in Phase 3, including the `SignalSourceConfig` row that `emit_signal` requires before it accepts the source.
- Slack destination template variables `investigation_notebook_url` and `insight_chart_url`.

## Risks

- **Consent gate.** Scout runs refuse to start without AI data processing approval. Alerts with the agent enabled in unapproved orgs would stop being investigated. Surface it in the UI before flipping the flag, and have the resume handler mark the check SKIPPED with a reason the alert page can show.
- **Latency.** Sandbox spin-up plus a 15 minute cap. Mitigated by the safety net; measure before cutover.
- **Concurrency.** Per-alert lanes are new to the harness. Test the single-flight and stale-run reaping under two concurrent alerts on one team.
- **Cost.** A sandbox lease per investigation is more expensive than an in-process LLM loop. The per-episode cap and the cooldown bound it. Report cost per run in the shadow phase.
- **Ownership split.** The skill lives under `products/signals/skills/`, the trigger under `posthog/temporal/alerts/`. Agree who reviews skill changes.
- **Temporal sandbox.** The alert check workflow already imports lazily to avoid the workflow sandbox restrictions. The new facade call goes in an activity, not the workflow body.

## Open questions

1. Should true positives become inbox reports (report channel) or stay as weak signals? This decides whether the inbox card and signal source survive.
2. Is the 15 minute scout runtime cap acceptable as the investigation ceiling, or does the alert lane need its own cap?
3. Does the metrics-alert investigation (no LLM) join this later as a second trigger context, or stay separate?
4. Should the skill be forkable per team like other canonical scouts, so a team can add domain rules, or locked as a system skill?
5. Who owns the skill file and its evals: alerts or signals?
