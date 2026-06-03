# Spec: persistent logs for the agent runtime

## Context

Per-session logs today live in a Redis LIST (`session_logs:<id>`, capped at 1k entries, 1h TTL) written by `agent-runner` and read through `agent-janitor`'s `/internal/sessions/:id/logs`, which Django proxies to the frontend / CLI.

That's a hack we want to drop. **Nothing in this path is released yet**, so we cut over in one shot — no dual-write, no shadow-read, no feature flag. The replacement:

- **Write** session logs into the existing ClickHouse `log_entries` table (same one CDP uses for hog function logs / batch exports / etc.), using a new `log_source = "agent_runtime"`. No new schema.
- **Read** from ClickHouse directly in Django via the existing [`fetch_log_entries`](../../posthog/api/log_entries.py) helper. The proxy URL stays; only its implementation changes from "HTTP to janitor" to "ClickHouse query." Same response shape, so frontend / CLI only need polling-cadence + cursor tweaks.
- **Drop Redis** from the log path entirely. Delete the janitor route, delete the `RedisSessionLogStore`, delete the bus-side log subscribe API.
- **Polling at 5s** with a timestamp-cursor (`?after=<ts>`). No SSE streaming for v1.

Streaming logs becomes a follow-up problem (Kafka tail / WebSocket fan-out). For now polling is good enough and matches what the frontend already does.

A **second pass** later will hook up `app_metrics2` for session-level counters (success/failure/awaiting_input by tool, cost per session, etc.). Schema fits naturally; out of scope here.

## Schema mapping

Reuse [`log_entries`](../../posthog/clickhouse/log_entries.py) as-is. ORDER BY `(team_id, log_source, log_source_id, instance_id, timestamp)`, partition `toYYYYMMDD(timestamp)`, TTL 90 days, sharded with a distributed table on top.

| Column          | What we put in it                                                                                                                                                                       |
| --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `team_id`       | `AgentApplication.team_id`                                                                                                                                                              |
| `log_source`    | constant `"agent_session"`                                                                                                                                                              |
| `log_source_id` | `AgentApplication.id` (UUID as string). "All logs for app X" rolls up cheaply across sessions.                                                                                          |
| `instance_id`   | `session_id` (UUID as string). Primary filter in the per-session view. Goes after `log_source_id` in the ORDER BY so it stays selective.                                                |
| `timestamp`     | event time, `DateTime64(6, 'UTC')`                                                                                                                                                      |
| `level`         | `INFO` for everything normal. `ERROR` for `error` events, `tool_result.ok=false`, `session_failed`, runner exceptions. `WARNING` reserved (no current callsites). `DEBUG` unused in v1. |
| `message`       | **Flat text with a self-describing `[kind]` prefix.** One row per entry. No JSON encoding; structured fields are flattened into the line. Examples below.                               |

### Message format

Plain text, one entry per row. Prefix carries the kind so the line is self-describing without parsing. The frontend renders these as flat log lines (one line per entry, color-coded by `level` and prefix) — not as typed cards.

```text
[meta]  session_init
[meta]  awaiting_input prompt="what'd you like to know about HN?"
[chat]  user: where are the hot AI stories?
[chat]  assistant: I'll check Hacker News for you…
[tool]  http.fetch@v1.get url=https://hacker-news.firebaseio.com/v0/topstories.json → 200 ok (124ms)
[tool]  slack@v1.chat.postMessage channel=C0123 ts=1716139384.001 → ok
[event] turn_completed
[error] anthropic 429 rate_limit_exceeded
```

Prefix vocabulary (lock these as a small enum in `agent-core`):

- `[meta]` — meta tools (`session_init`, `awaiting_input`, `session_end`, `get_trigger_payload`)
- `[chat]` — assistant / user / system message turns
- `[tool]` — tool calls + their results (success and failure)
- `[event]` — coarse turn-level events (`turn_started`, `turn_completed`)
- `[error]` — errors and failed tool calls

**Why flat text, not JSON-in-message:** smaller rows in CH, greppable in metabase / `clickhouse-client` without parsing, simpler frontend (no card-vs-line discriminated rendering). We can always switch to JSON later by changing the writer; no schema change needed.

**Tradeoff we accept:** we lose the structured args / result objects for tool calls. The frontend can't open a "show full args" expandable. If we ever need that back, a sidecar column or a separate structured log gets added — but the surface that exists today (a session-logs panel showing entries) works fine with flat lines.

## Write path

```text
agent-runner ──┐
               │  one Kafka message per SessionLogEntry
               ▼
        topic: log_entries
               │
               ▼
   existing log-entries CH consumer (already running for CDP)
               │
               ▼
        log_entries  (sharded + distributed)
```

We use **the same Kafka topic** CDP writes to (`log_entries`) and **the same ClickHouse consumer** that already drains it. Zero new infra.

### What changes in agent-runner

1. **Stop writing to `RedisSessionLogStore`.** Remove the `cache.disposables`-style append calls in [`services/agent-runner/src/worker.ts`](../../services/agent-runner/src/worker.ts) and the ass-server bridge.
2. **Replace with a Kafka producer call.** Same callsites; same `SessionLogEntry` payload; the entry gets wrapped into a `log_entries` row and produced.

### New code in `agent-core` (vendored, not imported from `nodejs/`)

Three new files, ~300 lines total:

- **`services/agent-core/src/log-entries/types.ts`** — `interface LogEntry { team_id; log_source; log_source_id; instance_id; timestamp; level; message }`. Mirrors what's in [`posthog/clickhouse/log_entries.py`](../../posthog/clickhouse/log_entries.py) line-for-line.
- **`services/agent-core/src/log-entries/producer.ts`** — thin `KafkaLogProducer`:
  - constructor takes a `kafkajs` (or `node-rdkafka`) instance + topic name (env-configurable, defaults to `"log_entries"`).
  - `append(LogEntry): void` enqueues in an in-memory array.
  - background flush every 500ms (or when the array crosses, say, 50 entries / 1MB) — `send({ messages: [...] })` batch.
  - `flush()` for shutdown.
  - serialization: `JSON.stringify(...)` of the row; identical to what CDP's `hog-function-monitoring.service` does.
  - **port `safeClickhouseString`** from [`nodejs/src/utils/db/utils.ts`](../../nodejs/src/utils/db/utils.ts) (escapes control chars). Maybe 5 lines.
- **`services/agent-core/src/log-entries/session-logger.ts`** — domain wrapper:
  - `SessionLogger.forSession({ teamId, applicationId, sessionId })` returns an object with `appendEvent(SessionEvent)` and `appendLog({ level, message, extra? })`.
  - Maps the `SessionLogEntry` to a `LogEntry` row (level derivation, JSON-encoding the entry into `message`, current timestamp).
  - Drops it into the shared `KafkaLogProducer`.

Wire-up: `agent-runner`'s bootstrap (`src/index.ts`) constructs the producer + shared logger once. The bridge + worker take a `SessionLogger` instead of a `SessionLogStore`. Replacement is mechanical — `logStore.append({ kind: 'event', ...evt })` becomes `sessionLogger.appendEvent(evt)`.

### Kafka config

- Topic: `log_entries` (or `KAFKA_LOG_ENTRIES_TOPIC` env override — matches CDP's pattern).
- Producer config: copy the minimum subset of [`nodejs/src/cdp/outputs/producers.ts`](../../nodejs/src/cdp/outputs/producers.ts) — `linger.ms=100`, `compression.type=lz4`, plus the broker addresses. Read from `KAFKA_HOSTS` (existing env var). One producer instance shared by the whole agent-runner process.
- Library: **lean kafkajs** for v1. `node-rdkafka` is faster but heavier to set up and not currently in `agent-core`'s deps. Log volume is low enough (one message per turn / tool call) that kafkajs throughput is fine.

## Read path

Django queries ClickHouse directly. **The janitor logs endpoint goes away** — Django already has a ClickHouse client.

### Django endpoint

Rewrite the existing [`AgentApplicationSessionProxyViewSet.logs`](../../products/agent_platform/backend/api.py) action body to query ClickHouse instead of proxying to janitor. Same URL, same response shape:

```text
GET /api/projects/:project_id/agent_applications/:slug/sessions/:session_id/logs/?after=<ts>&limit=<n>
→ { entries: SessionLogEntry[], next_after: string | null }
```

The implementation is one helper call:

```python
rows = fetch_log_entries(
    team_id=team_id,
    log_source="agent_session",
    log_source_id=str(application.id),
    instance_id=str(session_id),
    after=parse_after(request.query_params.get("after")),
    limit=int(request.query_params.get("limit", 200)),
)
# rows are DESC by timestamp; oldest first for the UI
entries = [
    {"timestamp": r["timestamp"].isoformat(), "level": r["level"], "message": r["message"]}
    for r in reversed(rows)
]
next_after = rows[0]["timestamp"].isoformat() if rows else None
return Response({"entries": entries, "next_after": next_after})
```

(The wire shape changes from today's `{ kind: 'event'\|'log', ... }` discriminated union to a simpler `{ timestamp, level, message }` array. The session-logs UI and CLI need a small render change — see Frontend / CLI below.)

**Why `fetch_log_entries` and not HogQL.** Both work. `fetch_log_entries` already exists, hits the same table, returns dicts ready to use, and is what the hog-function logs UI uses today. HogQL would give us team-scoping for free and is the modern path, but it's more boilerplate (query AST + runner + parsing) for a query that's already a one-liner against a known table. If we want to expose agent logs in a HogQL-queryable surface later (insights / dashboards), we add that on top of the same Kafka write path — no migration needed.

`next_after` = the timestamp of the newest entry (or `null` if empty). The client passes it back next poll. Empty result → keep the same `after` cursor.

### Frontend + CLI polling change

In [`products/agent_platform/frontend/sessionLogsLogic.ts`](../../products/agent_platform/frontend/sessionLogsLogic.ts):

- Bump poll interval `2s` → `5s`.
- Track the last `next_after` cursor; pass it as `?after=` on subsequent polls.
- Append only new entries to the rendered list (today: replaces whole list each poll).
- Render each entry as a single line with the `[kind]` prefix coloured by level. Drop the discriminated card components — flat list of `<timestamp> <level> <message>` rows.

In `packages/ass-cli/src/commands/logs.tsx`:

- Same `?after=` cursor + 5s cadence.
- Render `message` as-is (the prefix is already in the string). Use `level` for line colour: ERROR → red, INFO → default, WARNING → yellow.

## What gets removed

In Phase 2 (cutover):

- [`services/agent-core/src/session-logs/store.ts`](../../services/agent-core/src/session-logs/store.ts) — the Redis log store. Keep `SessionLogEntry` type (move into `log-entries/types.ts` or a shared `types.ts`); delete the `RedisSessionLogStore` class + `NullSessionLogStore` stub.
- [`services/agent-janitor/src/routes/logs.ts`](../../services/agent-janitor/src/routes/logs.ts) — the entire route.
- [`AgentApplicationSessionProxyViewSet.logs`](../../products/agent_platform/backend/api.py) action — replaced by the new direct-CH action (probably on the same viewset; the existing path stays, only the implementation changes).
- Redis log-related env wiring in `agent-runner` and `agent-janitor` bootstraps.
- The `session_logs:<id>:stream` pub/sub channel and the `RedisSessionLogStore.subscribe` API — nothing reads from it today (it was designed for SSE; SSE never landed).

The session-bus pub/sub (used by `agent-ingress` to fan SSE events to live `/listen/:id` consumers, e.g. the chat UI) **stays** — that's a different surface (live events, not durable logs) and the chat client depends on it. Only the _log store_ Redis path goes away.

## Phases

Two phases. No dual-write — Redis path is ripped out as the Kafka path lands.

### Phase 1 — Producer scaffolding in agent-core

- New `log-entries/{types,producer,session-logger}.ts` files. Producer is `kafkajs`-based, ~300 lines incl. tests.
- `SessionLogger.forSession({ teamId, applicationId, sessionId })` is the API agent-runner calls. Internally formats the `[kind]` prefix + writes a `LogEntry` row.
- No callers yet; pure library work. Unit tests with a fake producer.
- Env wiring: `KAFKA_HOSTS`, `KAFKA_LOG_ENTRIES_TOPIC`. Both default to the same values CDP uses.
- Demo: green tests, library is importable.

### Phase 2 — Cutover

Single coordinated change across agent-runner, janitor, Django, frontend, CLI. Lands together because the wire shape changes:

- **agent-runner**: every `logStore.append({ kind: ... })` callsite replaced with the matching `sessionLogger.appendXxx(...)`. Construct the producer + base logger at bootstrap.
- **agent-runner / agent-core**: remove `RedisSessionLogStore` from runner config + agent-core exports.
- **agent-janitor**: delete `src/routes/logs.ts` and the `SessionLogStore` plumbing.
- **Django**: rewrite `AgentApplicationSessionProxyViewSet.logs` to call `fetch_log_entries`. Return the new wire shape `{ entries: [{ timestamp, level, message }], next_after }`.
- **Frontend**: render flat lines; switch to 5s + cursor.
- **CLI**: same wire change in `ass logs`.

Demo: end-to-end run, frontend shows incoming log lines at 5s cadence, no Redis dependency in the log path. Janitor logs route 404s (gone). `select * from log_entries where log_source='agent_session'` shows the rows in CH.

## Decisions locked

1. `log_source = "agent_session"`.
2. `log_source_id = AgentApplication.id`, `instance_id = session_id`.
3. `level`: INFO default; ERROR for failures (`error` events, `tool_result.ok=false`, `session_failed`, runner exceptions); WARNING reserved; DEBUG unused.
4. `message`: flat text with `[meta]` / `[chat]` / `[tool]` / `[event]` / `[error]` prefix. No JSON-in-message. Frontend renders flat log lines.
5. No dual-write. Cutover is a single coordinated change.
6. Search: ILIKE on `message` (already supported by `fetch_log_entries`). No structured filtering in v1.

## Follow-ups (out of scope here)

- **Streaming.** SSE on logs becomes a Kafka tail layered on top of the same producer. Polling is fine for v1.
- **`app_metrics2`.** Same Kafka path + an aggregator copied from [`nodejs/src/common/services/app-metrics-aggregator.ts`](../../nodejs/src/common/services/app-metrics-aggregator.ts). First useful metrics: `agent_session.{started,completed,failed,canceled}`, `agent_tool_call.{success,error}` per tool, `agent_token_usage`. ~100 lines on top of what we ship here.
- **Structured tool args/result.** If the "expand to see args" UX comes back, we either add a JSON sidecar column or write a parallel structured stream.

## Files to touch / add

**New in `services/agent-core/`:**

- `src/log-entries/types.ts` — `LogEntry` row + `LogLevel` enum
- `src/log-entries/producer.ts` — `KafkaLogProducer` (kafkajs, batched in-process flush)
- `src/log-entries/session-logger.ts` — `SessionLogger.forSession` wrapper
- `src/log-entries/__tests__/*` — producer batching, level derivation, serialization

**Changed in `services/agent-runner/`:**

- `src/index.ts` — construct `KafkaLogProducer` + base `SessionLogger`
- `src/worker.ts` — replace `logStore.append(...)` with `sessionLogger.appendEvent(...)`
- `src/ass-server-bridge.ts` — same
- `src/config.ts` — `KAFKA_HOSTS`, `KAFKA_LOG_ENTRIES_TOPIC` env vars

**Changed / deleted in `services/agent-janitor/`:**

- `src/routes/logs.ts` — delete (Phase 5)
- `src/index.ts` — drop the `SessionLogStore` construction (Phase 5)

**Changed in `products/agent_platform/backend/`:**

- `api.py` — `AgentApplicationSessionProxyViewSet.logs` action rewritten to call `fetch_log_entries` instead of HTTP-proxying to janitor
- Tests: cover the new query path + `?after=` cursor semantics

**Changed in `products/agent_platform/frontend/`:**

- `sessionLogsLogic.ts` — 5s poll interval, `?after=` cursor handling, append-only render

**Reusable from `posthog/`:**

- [`posthog/clickhouse/log_entries.py`](../../posthog/clickhouse/log_entries.py) — schema (no change)
- [`posthog/api/log_entries.py:69`](../../posthog/api/log_entries.py) — `fetch_log_entries` helper (reuse as-is)
- [`nodejs/src/utils/db/utils.ts`](../../nodejs/src/utils/db/utils.ts) — `safeClickhouseString` (copy ~5 lines)

## Estimate

Phases 1–3 are ~2 days of work each. Phase 4 frontend touch is ~half a day. Phase 5 cleanup is ~half a day. Order matters but each phase is independently safe to ship and revert.
