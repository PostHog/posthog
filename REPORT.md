# Agent run telemetry: PostHog Code cloud tasks → PostHog Logs + APM

This branch is one half of a two-repo change; the companion branch is `posthog-code/agent-run-otel-telemetry` in `PostHog/code`.
This repo (`PostHog/posthog`) carries the configuration/injection side; `PostHog/code` carries the telemetry emitter inside the agent.

## Goal

Cloud task runs executed by PostHog Code should be observable in PostHog itself:
every run's lifecycle metadata delivered as OTel **logs** into the Logs product, and one OTel **trace** per run (root span, per-turn spans, per-tool-call spans) into APM, with logs and spans cross-linked via `trace_id`/`span_id`.

Hard requirements:

- **Filterable per user**: the Logs UI must answer "show me everything cloud runs did for this user" directly, so `user_id`/`distinct_id` (plus `team_id`, `task_id`, `run_id`) are OTel resource attributes, which PostHog Logs facets via `resource_fingerprint`.
- **Cloud tasks only** for now; desktop local runs do not export session telemetry.
- **Metadata only**: the S3 session log remains the source of truth for full transcripts. Telemetry never carries prompts, agent message/thought text, tool arguments, or tool output.

## Background: what existed before

- Agent session logs flow from the sandbox `agent-server` through `SessionLogWriter` to the Django endpoint `POST /api/projects/{team}/tasks/{task}/runs/{run}/append_log/`, which appends NDJSON to S3 (`TaskRun.append_log`, 30-day TTL). Two more delivery legs exist: an NDJSON event-ingest stream and SSE to connected clients.
- A February attempt at OTel logs export (`OtelLogWriter`, commits `6abadc79` → `99a3aea8` → `8876c8fb` in `PostHog/code`) was unwired, and its default endpoint `/i/v1/agent-logs` does not exist in the ingest service; it would 404 today.
- The correct ingest is the `capture-logs` Rust service (`rust/capture-logs/`): `POST /i/v1/logs` and `POST /i/v1/traces`, OTLP http/protobuf or http/JSON, auth `Authorization: Bearer <project API key>`, 2 MB request cap, billed by uncompressed bytes, severity normalized to lowercase, prod host `https://us.i.posthog.com`.
- Working dogfood precedents followed here: the desktop Electron transport (`posthog-code-desktop` → `/i/v1/logs`), the engineering-analytics CI log emitter, the streamlit sandbox proxy (env-injected OTLP config), and the plugin-server metrics exporter (telemetry off unless URL + token are both set).

## Architecture

```
sandbox (agentsh)
└── agent-server (PostHog/code, packages/agent)
    ├── ACP streams (tapped) ──► SessionLogWriter ──► Django append_log ──► S3   (product log, unchanged)
    │                                   │
    │                                   └─ sink ──► OtelRunTelemetry
    │                                                ├─ log records ──► POST {POSTHOG_AGENT_OTEL_LOGS_URL}
    │                                                └─ RunTraceBuilder spans ──► POST {POSTHOG_AGENT_OTEL_TRACES_URL}
    └── terminal error events ──────────────────────► mirrored into OtelRunTelemetry directly

capture-logs (Rust) ──► Kafka ──► ClickHouse (logs / trace_spans) ──► Logs + APM UI
```

Telemetry is emitted **from inside the sandbox** by the agent-server process, deliberately independent of the Django/S3 product path: if `append_log` is degraded, telemetry still flows, and a broken product log pipeline is exactly the failure telemetry must capture.
Egress works because `*.posthog.com` is in the agentsh `INFRASTRUCTURE_DOMAINS` allowlist (prod) and the new `SANDBOX_AGENT_OTEL_*_URL` hosts join the DEBUG-only firewall list (local dev).

## What ships per run

### Log records (service.name=posthog-code-agent)

Resource attributes on every record: `service.name`, `service.version` (agent version), `run_id`, `task_id`, `team_id`, `user_id`, `distinct_id`, `device_type` (`cloud`), `adapter` (`claude`/`codex`), `run_mode` (`interactive`/`background`).

Exported events (allowlist, everything else is dropped):

| Event | Severity | Notable attributes |
| --- | --- | --- |
| `_posthog/run_started` | info | `agent_version`, `session_id` |
| `_posthog/sdk_session` | info | `adapter`, `session_id` |
| `_posthog/usage_update` (and the `session/update` variant) | info | `tokens_input/output/cached_read/cached_write`, `cost_usd` |
| `_posthog/turn_complete` | info | `stop_reason` |
| `_posthog/task_complete` | info | `stop_reason` |
| `_posthog/error` | **error** | `error_source`, `stop_reason`; body is the generic "run error" — the raw message is free text that can embed prompt/repo content, so it stays in the session log and the run's `error_message` |
| `_posthog/progress` | info | `progress_group/step/status` |
| `_posthog/git_checkpoint`, `_posthog/branch_created` | info | `branch` |
| `_posthog/mode_change`, `_posthog/compact_boundary` | info | |
| `_posthog/permission_request/response/resolved` | info | `request_id`, `tool_call_id` (identifiers only; tool content excluded) |
| `session/update: tool_call` | info | `tool_call_id`, `tool_kind`, `tool_status` (no title, no rawInput) |
| `session/update: tool_call_update` (terminal only) | info / warn on `failed` | `tool_call_id`, `tool_status` |

Deliberately dropped: `agent_message`, `agent_message_chunk`, `agent_thought_chunk`, `user_message`, `session/prompt` bodies, in-progress `tool_call_update` snapshots (they re-send the growing tool input/output), `available_commands_update`, `_posthog/console` (free-text agent-server diagnostics interpolate arbitrary data — e.g. the prompt preview logged on user-message handling and stringified extension params — so exporting them would leak content; they stay in the S3 log and event-ingest stream), and any unknown method (fail-closed allowlist).
Bodies are capped at 2000 chars; free-text attribute values at 200 chars (the `log_attributes` faceting table only indexes key/value pairs under 256 chars).

### APM trace (one per run)

- `task_run` root span (kind SERVER): opened at session init, closed at session cleanup. Status is resolved at shutdown from the latest turn outcome (the sandbox never emits `task_complete` for successful runs — the terminal "completed" status is decided by the workflow outside — so the last turn is the in-sandbox success signal): OK when the last turn ended with `end_turn`, ERROR on `_posthog/error` (an error always wins, later turn completions cannot flip it back; `error_source` lands as a root-span attribute while the raw message is withheld — see the error row above) or when the last turn stopped with `error`, unset otherwise (cancelled / refused / timed out / no completed turns). Resolving at shutdown rather than per-turn means an early clean turn cannot leave a stale OK on a run whose final turn was cancelled.
- `turn` child spans: opened on each ACP `session/prompt` (used purely as a boundary marker; its content is never read), closed on `_posthog/turn_complete`; attributes `turn_index`, `stop_reason`, plus the turn's token counts and `cost_usd` lifted from usage updates, so APM can rank slow or expensive turns directly.
- `tool_call:<kind>` grandchild spans (`execute`, `read`, `edit`, ...): opened on `tool_call`, closed on the terminal `tool_call_update`; status ERROR on `failed`; attributes `tool_call_id`, `tool_kind`, `tool_status`. Per-kind span names stay low-cardinality and make APM latency breakdowns by tool kind useful.
- Robustness: orphaned spans are closed (status unset) and exported at shutdown; a new prompt while a turn is open closes the stale turn; duplicate `tool_call` events are idempotent; a run error cascades ERROR status to the open turn and the root, and closes still-open tool spans as ERROR with `tool_status=interrupted` so APM never shows a healthy-looking active tool under a failed run.
- Every log record is emitted under the OTel context of the span it belongs to (tool logs on the tool span, lifecycle logs on the root), so `trace_id`/`span_id` land in the `logs` table columns and the UI links Logs ⇄ trace waterfall.

### Delivery timing

Telemetry is near-realtime, not end-of-turn: records are created the moment each notification flows through the writer and batched for at most 2 s (`BatchLogRecordProcessor` / `BatchSpanProcessor`, `scheduledDelayMillis` 2000).
Spans export when they end (tools mid-turn, turns at `turn_complete`, root at cleanup).
Flush safety nets: an explicit flush after a terminal error in `signalTaskComplete`, a full shutdown-flush in `cleanupSession` (which SIGTERM reaches via `stop()`), so sandbox teardown cannot eat the tail of a run's telemetry.
Flush and shutdown are best-effort and per-signal independent (`Promise.allSettled`), and every export is capped at 5 s (`exportTimeoutMillis`, down from the SDK's 30 s default), so a rejecting or hanging traces endpoint can neither starve log delivery nor hold up session cleanup.

## Changes in PostHog/code (companion branch)

- `packages/agent/src/otel-telemetry.ts` (renamed from `otel-log-writer.ts`): `OtelRunTelemetry`, the single `SessionLogSink` owning the OTLP log exporter and (when a traces URL is configured) the `RunTraceBuilder`. Contains the pure `mapNotificationToLogRecord()` allowlist mapper. Fixes the dead `/i/v1/agent-logs` default. Never throws into the run; ignores entries for other sessions.
- `packages/agent/src/otel-trace-builder.ts` (new): `RunTraceBuilder`, the span state machine described above; `handle(entry)` returns the context each log record should attach to.
- `packages/agent/src/otel-attributes.ts` (new): shared pure helpers (`strAttr`, `numAttr`, `usageAttributes`, truncation, caps).
- `packages/agent/src/session-log-writer.ts`: optional `sinks: SessionLogSink[]`, teed in `appendRawLine` after the entry is built; a throwing sink warns once and can never break product log persistence; message chunks never reach sinks. `SessionContext` moved here from the otel module.
- `packages/agent/src/server/agent-server.ts`: builds the telemetry per session from config (`createRunTelemetry`), passes it as the writer sink, stores it on the session, shuts it down in `cleanupSession`, flushes after terminal errors, and mirrors `enqueueTaskTerminalEvent` payloads into it directly (terminal `_posthog/error` events bypass `SessionLogWriter`, and a failed run is exactly what telemetry must record). Fatal crashes (`reportFatalError`, the uncaught-exception/unhandled-rejection path) also mirror an error record (`error_source=agent_server_crash`) and shut telemetry down, so hard process deaths reach the telemetry project instead of vanishing.
- `packages/agent/src/server/bin.ts` + `server/types.ts`: zod-validated env `POSTHOG_AGENT_OTEL_LOGS_URL`, `POSTHOG_AGENT_OTEL_LOGS_TOKEN`, `POSTHOG_AGENT_OTEL_TRACES_URL` → `AgentServerConfig.otelLogsUrl/otelLogsToken/otelTracesUrl`. Telemetry is off unless the logs pair is set; spans additionally require the traces URL (per-signal kill switch).
- `packages/agent/src/types.ts`: the February `OtelTransportConfig`/`AgentConfig.otelTransport` remain as `@deprecated`, ignored stubs — `@posthog/agent` is a published package, so removing exported types is an API break reserved for a major.
- Dependencies: `@opentelemetry/api`, `@opentelemetry/sdk-trace-base`, `@opentelemetry/exporter-trace-otlp-http`, version-aligned with the existing logs SDK (0.208.x experimental / 2.x stable line).
- Tests (74 passing): parameterized log-mapping matrix, hard privacy tests asserting exported payloads never contain tool args/titles/output or raw error messages, per-user resource attributes, session-mismatch guard, never-throws guard, sink isolation in `SessionLogWriter`, and five trace tests (span tree + statuses + attributes, log⇄span id correlation, error cascade incl. interrupted tools, orphan export on shutdown, log shutdown isolated from a failing traces endpoint).
- `packages/agent/README.md`: documents the env vars and behavior.

## Changes in PostHog/posthog (this branch)

- `posthog/settings/temporal.py`: new optional settings `SANDBOX_AGENT_OTEL_LOGS_URL`, `SANDBOX_AGENT_OTEL_LOGS_TOKEN`, `SANDBOX_AGENT_OTEL_TRACES_URL` (all default unset = telemetry off).
- `products/tasks/backend/temporal/process_task/utils.py`: `get_sandbox_otel_env_vars()` maps those settings to the sandbox env vars, gated on the logs pair; called from **both** env assembly paths so fresh provisioning and snapshot-resume behave identically:
  - `activities/provision_sandbox.py` `_build_environment_variables`
  - `utils.py` `build_sandbox_environment_variables` (used by `create_sandbox_from_snapshot`)
- `products/tasks/backend/constants.py`: the three env keys added to `RESERVED_SANDBOX_ENVIRONMENT_VARIABLE_KEYS` so user-supplied SandboxEnvironment vars cannot override them.
- `products/tasks/backend/logic/services/agentsh.py`: `SANDBOX_AGENT_OTEL_LOGS_URL`/`SANDBOX_AGENT_OTEL_TRACES_URL` added to `_DEBUG_SANDBOX_URL_SETTINGS` so local-dev hosts pass the agentsh syscall firewall (prod egress already covered by `*.posthog.com`).
- `products/tasks/backend/logic/services/docker_sandbox.py`: `POSTHOG_AGENT_OTEL_LOGS_URL`/`POSTHOG_AGENT_OTEL_TRACES_URL` added to `_DOCKER_URL_ENV_KEYS` so localhost URLs are rewritten to `host.docker.internal` for local Docker sandboxes.
- Tests: parameterized gating matrix on `_build_environment_variables` (5 rows: full config, logs-only, partial configs, traces-without-logs all correctly gated) and a `SimpleTestCase` wiring guard on the snapshot-resume path.
- `docs/internal/sandboxes-setup-guide.md`: local-dev setup section for the new settings.

## Key design decisions

1. **Emit from the sandbox, not from Django.** Independence from the product log path (see Architecture), matching the streamlit sandbox precedent. The Django-tee alternative would add an outbound call to a hot API path and go dark precisely when `append_log` breaks.
2. **`POSTHOG_`-prefixed env vars instead of standard `OTEL_*` names.** The sandbox env is inherited by the user's own processes (their tests, their apps). Standard `OTEL_EXPORTER_OTLP_*` vars would make any OTel SDK in user code silently auto-export the user's telemetry into our internal project. Custom names mean only agent-server reads the config.
3. **`service.name=posthog-code-agent`, not `posthog-code`.** `service.name` identifies the emitting process, not the product: the desktop app already ships its process logs as `posthog-code-desktop`, and `service_name` is both the primary Logs UI facet and part of the ClickHouse sort key `(team_id, service_name, timestamp)`, so component-level names keep streams separable and queries narrow. House pattern matches (`posthog-django-*`, `node-*`, `github-ci-logs`).
4. **Fail-closed allowlist for content.** Only known lifecycle events are exported; unknown methods are dropped. This is a privacy boundary (customer prompts/repo content must not reach the telemetry project) and a cost control (logs are billed by bytes; in-progress tool snapshots re-send growing output).
5. **Generic `SessionLogSink` instead of hardcoding OTel into `SessionLogWriter`.** The February attempt was removed partly because of hard coupling; the sink interface keeps the writer single-purpose, is desktop-neutral (no sinks wired there), and isolates sink failures.
6. **Terminal-error mirrors.** Two paths bypass `SessionLogWriter` and are mirrored into telemetry explicitly: `enqueueTaskTerminalEvent` (agent-server-sourced run errors, which feed only the event-ingest stream) and `reportFatalError` (unrecoverable crashes, which mark the run failed via the API with no session log involvement). Without the mirrors the most important records, failed and crashed runs, would be missing from telemetry.
7. **Per-signal kill switch.** Logs and spans have separate URLs; unsetting the traces URL disables spans without touching logs, and unsetting either of the logs pair disables everything.
8. **Token exposure is acceptable by design.** The sandbox receives a project API key of the telemetry project: a write-only, public-by-design key class (the same class that ships in client SDKs), far weaker than the `POSTHOG_PERSONAL_API_KEY` already present in the sandbox. Worst case is junk telemetry writes; `capture-logs` has a token drop list as the kill switch.

## Verification

- `PostHog/code`: 74 tests pass in the agent package (including the new telemetry suite), `tsc --noEmit` clean via turbo, biome clean on all touched files (one pre-existing warning untouched). The package's pre-existing test failures in this environment (missing Postgres/git fixtures) were confirmed byte-identical with and without these changes by running the failing files against a stashed tree.
- `PostHog/posthog`: 21 tests pass across `test_provision_sandbox.py` and the new `TestBuildSandboxEnvironmentVariables`; `ruff check`/`format` clean on all touched files. DB-dependent suites in this sandbox fail identically with and without the change (no Postgres available).
- Local-dev routing verified: Caddy serves `/i/v1/logs`/`/i/v1/traces` on `localhost:8000` and proxies to `capture-logs`, and the Docker URL rewrite covers the new vars.

## Rollout runbook (what remains)

1. Choose the destination telemetry project and create/locate its project API key. Recommendation: the shared internal project where `posthog-code-desktop` logs and Code analytics already land, so desktop and cloud correlate in one Logs view (separable by `service_name`).
2. Set in prod US:
   - `SANDBOX_AGENT_OTEL_LOGS_URL=https://us.i.posthog.com/i/v1/logs`
   - `SANDBOX_AGENT_OTEL_LOGS_TOKEN=<project API key>`
   - `SANDBOX_AGENT_OTEL_TRACES_URL=https://us.i.posthog.com/i/v1/traces`
3. Run one cloud task; verify in the destination project: Logs filtered by `service.name=posthog-code-agent` (facet by `distinct_id`/`user_id`/`run_id`), and the APM trace for the run (`task_run` → `turn` → `tool_call:*` waterfall, logs linked from spans).
4. Add a saved Logs view and alerts (error severity on the service; volume anomaly), and watch billed bytes for a week; the event allowlist and body caps are the tuning knobs.
5. Optional follow-ups: unify the desktop transport with the new telemetry module; consider a shared `product` resource attribute across `posthog-code-*` services; sampling if volume warrants.

## Configuration reference

| Where | Name | Meaning |
| --- | --- | --- |
| Django settings | `SANDBOX_AGENT_OTEL_LOGS_URL` | Full OTLP logs ingest URL; unset = telemetry off |
| Django settings | `SANDBOX_AGENT_OTEL_LOGS_TOKEN` | Project API key of the telemetry project; unset = telemetry off |
| Django settings | `SANDBOX_AGENT_OTEL_TRACES_URL` | Full OTLP traces ingest URL; unset = spans off, logs unaffected |
| Sandbox env (injected) | `POSTHOG_AGENT_OTEL_LOGS_URL` / `_TOKEN` / `POSTHOG_AGENT_OTEL_TRACES_URL` | Read by `agent-server` (`bin.ts`); reserved keys, not user-overridable |
