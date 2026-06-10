# Ingress decision logs, available to the agent (and console)

**Status:** not started. Builds directly on the runner's existing
`KafkaLogSink → log_entries (ClickHouse)` pipeline; ingress just needs to be
wired into it.

## Problem

Ingress request logs only hit stdout/pino today
([`services/agent-ingress/src/routing/http-utils.ts`](../../../services/agent-ingress/src/routing/http-utils.ts):`requestLogger`).
When a real call gets rejected — a Slack event 403'd as `workspace_not_trusted`,
a `401 invalid_signature`, a `500 signing_secret_unresolved` — there's no
record an agent author (or the agent itself) can see. You have to be tailing
the pod. "Why did my bot ignore that message?" is unanswerable from the product.

## Idea

Reuse the runner's pipeline, but emit **ingress decision events keyed by
`application_id`** (not `session_id`). They then land in the same per-agent
`log_entries` view the console already renders
([`services/agent-console/src/lib/runnerReducer.ts`](../../../services/agent-console/src/lib/runnerReducer.ts) reads these),
and any agent-facing `log_entries` reader surfaces them for free.

Sink + wire format already exist:
[`services/agent-shared/src/runtime/log-sink.ts`](../../../services/agent-shared/src/runtime/log-sink.ts)
(`LogEntry`, `KafkaLogSink`, `toWire`). Runner reference wiring:
[`services/agent-runner/src/index.ts`](../../../services/agent-runner/src/index.ts):167.

## The decision that matters: curate, don't firehose

Two audiences — keep them on separate transports:

- **Platform/SRE humans** → stdout JSON → Loki/Grafana. **Already works** via
  pino. Do NOT duplicate into ClickHouse.
- **Agent authors + the agent itself** → curated decision events →
  `log_entries` keyed by `application_id`.

Do **not** push the raw access log (`requestLogger`) into Kafka:

- It runs before routing, so it has no `application_id` for most requests —
  and `log_entries` is tenant-scoped on `team_id`/`log_source_id`. Unattributable.
- healthz / bot scans / unresolved-slug probes = noise at per-team CH cost.

The events worth emitting happen **after `resolveAgent`**, where we already hold
`application.team_id` + `application.id`. Several are already `log.warn/info`
lines today — they'd just also go to the sink.

## Events to emit (per-agent, decision-level)

From the trigger handlers, after the agent is resolved:

- `request_rejected` — `workspace_not_trusted` (slack.ts:140), `invalid_signature`,
  `signing_secret_unresolved`, `no_slack_trigger`.
- `request_dropped` — `mention_only`, `mention_only_no_owned_thread`
  (already logged in [`services/agent-ingress/src/triggers/slack.ts`](../../../services/agent-ingress/src/triggers/slack.ts)).
- `session_enqueued` / `session_resumed` — include the real `session_id` in
  `data` so you can pivot ingress ↔ session.
- `elevation_required` — non-owner posted into an owner-only thread.

## Implementation sketch

1. **Generalize `LogEntry`** (`log-sink.ts`): add optional `log_source`
   (default `'agent_session'`); `toWire` reads it instead of hardcoding
   `AGENT_SESSION_LOG_SOURCE`. New source `'agent_ingress'`. When there's no
   session yet, use the access logger's `req_id` (the `x-request-id` it already
   mints) as `instance_id`; carry the real `session_id` in `data` once enqueued.

2. **Wire `KafkaLogSink` into [`services/agent-ingress/src/index.ts`](../../../services/agent-ingress/src/index.ts)**
   like the runner — `KAFKA_BROKERS` is already a platform config field, so it's
   free. `connect()` at boot, `disconnect()` in the shutdown handler. Thread the
   sink onto `BuildAppOpts` → `triggerDeps` (optional, like the other deps).

3. **Emit at the decision points.** Tiny helper, e.g.
   `deps.logs?.write([ingressEvent(app, { event, level, data })])`. Drop next to
   the existing warn lines. Fire-and-forget — `KafkaLogSink.write` already drops
   on broker failure, so it can't block or break the 3s Slack ack window.

   ```ts
   { ts, team_id: app.team_id, application_id: app.id,
     session_id: reqId, log_source: 'agent_ingress',
     level: 'warn', event: 'request_rejected',
     data: { trigger: 'slack', status: 403, reason: 'workspace_not_trusted',
             workspace, method, path, req_id } }
   ```

4. **Console** (phase 2): the log viewer already filters by
   `log_source_id = application_id`; add a `log_source` facet so ingress +
   session logs show in one per-agent timeline.

5. **Agent self-debugging** (the payoff): because rows land under the agent's own
   `application_id`, an existing `logs`-domain reader lets an SRE-type agent ask
   _"show my recent ingress rejections"_ with zero extra plumbing.

## Guardrails

- **No secrets in `data`** — status / reason / workspace-id / method / path /
  req_id only. Never raw bodies, tokens, signatures. (Workspace id is already
  public — it's in the 403 body.)
- **Tenant key is `application.team_id`**, not the platform `config.teamId`.
- Sink is **additive** — stdout access logging stays as-is for ops.

## Phasing

- **Phase 1** (~half a day): generalize `LogEntry`, wire the ingress sink, emit
  the ~6 decision events. Per-agent ingress debugging becomes visible in the
  console and readable by the agent.
- **Phase 2**: console `log_source` facet.
- **Phase 3** (optional): scrape pino stdout → Loki for the raw access firehose
  (SRE audience, no Kafka).

## Related

- [`session-failure-observability.md`](session-failure-observability.md) — the
  session-side analogue; same `log_entries` surface, different source.
- [`platform-llm-analytics.md`](platform-llm-analytics.md) — the other
  agent-readable telemetry stream.
