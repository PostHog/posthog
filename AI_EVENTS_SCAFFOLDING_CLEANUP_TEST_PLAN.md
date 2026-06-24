# Test plan — `ai_events` scaffolding cleanup (llma)

You are validating a change set against a **local** PostHog instance. You have the
same skills and memories as the author, but **none of the conversation** that produced
this plan. Everything you need is below. Read the whole document before acting.

---

## 0. What changed and why it matters

PR #64322 (`chore(llma): remove ai_events table migration scaffolding`), since merged up
to latest master, removed the feature-flag/dual-deployment scaffolding for the dedicated
`ai_events` ClickHouse table. The dedicated table is GA. The behavioural surface you must
verify is the **steady state** the cleanup leaves behind. Three things actually changed in
ways that are observable from outside the process:

1. **Read side (`posthog/hogql_queries/ai/ai_table_resolver.py`).** The flag-gated helper
   `execute_with_ai_events_fallback` is now `query_ai_events(..., fall_back_to_events: bool = False)`.
   When the `ai_events` query returns no rows it branches three ways:
   - `fall_back_to_events=True` → re-run against the shared `events` table and return that.
   - `fall_back_to_events=False` → probe `events` only to **classify the miss**, raising
     `AIEventsExpiredError` (row exists in `events` → it aged out of the 30-day `ai_events`
     TTL) or `AIEventsNotFoundError` (in neither).
   The manual-eval endpoint uses the raise path and maps the two errors to **distinct 404s**.
   `is_ai_events_enabled` and the `ai-events-table-rollout` flag are gone.

2. **Write side (`nodejs/.../split-ai-events-step.ts`).** The AI-event split is now
   **unconditional**: every AI event has the heavy `$ai_*` properties stripped from the
   `events` copy and the full event written to `ai_events`. The `INGESTION_AI_EVENT_SPLITTING_*`
   env vars are gone.
   Heavy (stripped) properties: `$ai_input`, `$ai_output`, `$ai_output_choices`,
   `$ai_input_state`, `$ai_output_state`, `$ai_tools`.

3. **Eval scheduler (`nodejs/src/evaluation-scheduler/`).** Collapsed from a dual
   `events`/`ai_events` deployment to a **single `ai_events` consumer**. Removed
   `LLMA_EVAL_SCHEDULER_TOPIC` / `_AI_TOPIC_TEAMS` and the team-partition logic.

There is also a frontend change (removal of the `AI_EVENTS_TABLE_ROLLOUT` flag gate in the
AI observability data logics) — see §“Cannot cover”.

---

## 1. Operating principles (read first — these define pass/fail)

- **LOCAL ONLY.** Every request targets `http://localhost:8010` and the local ClickHouse /
  Postgres. **Do not** use the `posthog-prod` MCP, and do not let any MCP tool run against
  the active (prod) environment. If you use the `posthog-local` MCP at all, confirm it is
  pinned to localhost first. When in doubt, use `curl` and `manage.py shell`.
- **Direct API + direct DB. No test scripts. No Playwright.** Drive everything with
  individual `curl` calls, `manage.py` one-off commands, and ClickHouse/Postgres queries.
  Do **not** author a `.py`/`.sh`/`.ts` test file or a pytest/jest suite. `manage.py`
  one-liners (e.g. `setup_local_api_key`, a `shell -c "..."` running `sync_execute`) are
  **setup/verification tooling**, not test scripts — those are allowed.
- **Three outcomes per check, always:**
  - **SUCCESS** — the exact, specified observable result occurred.
  - **FAILURE** — a specified contradicting result occurred (this is a real regression).
  - **NEITHER → INVESTIGATE** — anything else (auth error, validation error, connection
    refused, empty/ambiguous response, a dependency that isn't running). This is **not** a
    pass and **not** a fail; report it as "could not determine" with the raw evidence and
    move on. Never round a NEITHER up to SUCCESS or down to FAILURE.
- **Be honest about coverage.** Where a surface cannot be exercised this way, say so and say
  why — do not fabricate a proxy and call it covered.
- **Report raw evidence** (HTTP status + body, row counts, query-log tags) for every check,
  not just a verdict.

---

## 2. Preflight (do all of this before any test; a failure here BLOCKS dependent tests)

Run commands inside the dev environment (prefer `flox activate -- bash -c "..."` /
`hogli` if a bare command fails).

1. **Stack health.** Confirm the dev stack is up. Check process status with the `phrocs`
   MCP (`get_process_status`) or the `run-posthog` skill. You specifically need to know
   which of these are running, because each gates a different test group:
   - **Django web on :8010** — required for *all* API tests.
   - **ClickHouse** — required for seeding/verification.
   - **Temporal** — required only for the eval-runs **202 success** path (§C) and any real
     workflow execution.
   - **Node ingestion consumer (plugin-server / ingestion)** — required only for
     capture-based seeding and the write-path split (§C, §F).
   If a component is down, do not fail its tests — mark them **BLOCKED (cannot cover:
   <component> not running)**. You may start the stack (`./bin/start` / `hogli start`) if
   that is in scope for your run; otherwise just record the block.

2. **Auth — mint the deterministic dev key:**
   ```
   python manage.py setup_local_api_key
   ```
   This is DEBUG-only and idempotent. The key is fixed:
   `phx_dev_local_test_api_key_1234567890abcdef` (all scopes). Use it as
   `Authorization: Bearer phx_dev_local_test_api_key_1234567890abcdef` on every API call.
   - SUCCESS: command prints `Key: phx_dev_local_test_api_key_...`.
   - NEITHER: command errors (e.g. "only with DEBUG=True", no users) → resolve before
     continuing; all API tests are blocked until you have a working key.

3. **Identify the team + project token:**
   ```
   curl -s http://localhost:8010/api/projects/@current/ \
     -H "Authorization: Bearer phx_dev_local_test_api_key_1234567890abcdef" | jq '{id, name, api_token}'
   ```
   Record `TEAM_ID` (likely `1` locally) and `PROJECT_TOKEN` (`phc_...`, used for capture).
   All project-scoped routes below are `/api/projects/<TEAM_ID>/...`. (`/api/environments/<TEAM_ID>/...`
   is an equivalent dual route if you prefer.)

4. **Confirm the ClickHouse tables exist** (the cleanup assumes they're present):
   ```
   python manage.py shell -c "from posthog.clickhouse.client import sync_execute; \
     print(sync_execute('SHOW TABLES LIKE \'%ai_events%\''))"
   ```
   - SUCCESS: `ai_events` (and `sharded_ai_events`) are listed.
   - NEITHER: tables missing → CH migrations haven't run locally; seeding + read tests are
     blocked until they do (`migrate_clickhouse`).

---

## 3. Surface map (what we test vs. what we can't)

| # | Surface | Method | Needs |
|---|---------|--------|-------|
| A | eval-runs **not-found** 404 | API only | web, CH, an Evaluation |
| B | eval-runs **expired** 404 (distinct) | API + seed events-only row | web, CH, an Evaluation |
| C | eval-runs **success** 202 | API + ai_events row (capture) | web, CH, **Temporal**, ingestion |
| D | fallback read endpoints (summary / sentiment / offline_evals / personal spend) | API + seed | web, CH |
| E | trace read path (HogQL `ai_events` runner) | API (query) | web, CH |
| F | write-path split (events stripped + ai_events full) | capture + CH inspect | web, CH, **ingestion** |
| G | eval scheduler (Kafka→Temporal) | **cannot cover** (documented) | — |
| H | frontend flag-gate removal | **cannot cover** (no browser) | — |

The crown jewels of this PR are **A** and **B** — the expired-vs-not-found distinction.
They need neither Temporal, Kafka, nor ingestion, so they are the most deterministic and
should anchor your run.

---

## 4. One-time setup for the eval-runs tests (§A–C): create an Evaluation

The eval-runs endpoint requires an existing `Evaluation` row for the team. Create a minimal
one via the API so the request reaches the ClickHouse lookup (the part this PR changed).
Prefer `evaluation_type: "hog"` so the **success** path does not need an LLM provider key.

- Inspect required fields first (do not guess): read
  `products/ai_observability/backend/api/evaluations.py` and
  `products/ai_observability/backend/models/evaluations.py`, or the generated OpenAPI
  (`hogli build:openapi` output / `/api/schema/`). The `/improving-drf-endpoints` skill
  describes the serializer conventions.
- Create it:
  ```
  curl -s -X POST http://localhost:8010/api/projects/<TEAM_ID>/evaluations/ \
    -H "Authorization: Bearer phx_dev_local_test_api_key_1234567890abcdef" \
    -H "Content-Type: application/json" \
    -d '{ ...minimal valid hog evaluation... }' | jq '{id, evaluation_type, name}'
  ```
  Record `EVALUATION_ID`.
- SUCCESS: 201 with an `id`. NEITHER: 400 (adjust the body to satisfy the serializer — a
  harness problem, not a product result).

Pick a `TARGET_TS` you will reuse (an ISO-8601 timestamp, today's date — the lookup matches
on `toDate(timestamp)`). Generate fresh UUIDs per case (`uuidgen`).

---

## 5. Tests

### A. eval-runs — event not found → 404 "not found"  *(primary, no Temporal)*

The cleanest deterministic check. No seeding: just use a UUID that exists nowhere.

```
curl -s -o /tmp/a.json -w "%{http_code}\n" -X POST \
  http://localhost:8010/api/projects/<TEAM_ID>/evaluation_runs/ \
  -H "Authorization: Bearer phx_dev_local_test_api_key_1234567890abcdef" \
  -H "Content-Type: application/json" \
  -d '{"evaluation_id":"<EVALUATION_ID>","target_event_id":"<RANDOM_UUID>","timestamp":"<TARGET_TS>"}'
cat /tmp/a.json
```

- **SUCCESS:** HTTP **404** and body `{"error":"Event <uuid> not found"}`.
- **FAILURE:** HTTP 202 (claims it started for a non-existent event); **or** 404 with the
  *expired* message (`"...past the ai_events retention window..."`) — that means the
  not-found/expired classification is inverted; **or** HTTP 500.
- **NEITHER:** 400 (serializer rejected the body — fix the body), 401/403 (auth/scope),
  404 `"Evaluation <id> not found"` (your `EVALUATION_ID` is wrong), connection refused.

### B. eval-runs — event aged out → 404 "past the retention window"  *(primary, no Temporal)*

Produce a row that exists in `events` but **not** in `ai_events`. Two ways — pick by what's
running:

**B-seed (preferred if ingestion is up): capture, then delete from `ai_events`.**
1. Capture an `$ai_generation` (see §F for the exact capture call) with a known
   `UUID_B` and `timestamp = TARGET_TS`.
2. Wait until it appears in **both** tables (poll, see §F).
3. Delete it from `ai_events` only:
   ```
   python manage.py shell -c "from posthog.clickhouse.client import sync_execute; \
     sync_execute(\"ALTER TABLE sharded_ai_events DELETE WHERE team_id=<TEAM_ID> AND uuid='<UUID_B>'\")"
   ```
4. Poll until `SELECT count() FROM ai_events WHERE team_id=<TEAM_ID> AND uuid='<UUID_B>'`
   returns 0 while `SELECT count() FROM events WHERE ...` still returns ≥1 (mutations are
   async; wait for completion).

**B-seed (fallback if ingestion is down): insert an `events`-only row directly.**
Introspect the schema first (`SHOW CREATE TABLE sharded_events`) and insert the minimal
columns the probe needs to match (`team_id`, `uuid`, `event='$ai_generation'`,
`timestamp` on `TARGET_TS`'s date, `distinct_id`, `created_at`, `_timestamp`). Confirm
`SELECT count() FROM events WHERE team_id=<TEAM_ID> AND uuid='<UUID_B>'` ≥ 1 and the same
against `ai_events` = 0.

Then call eval-runs with `target_event_id=UUID_B`, `timestamp=TARGET_TS` (same shape as §A).

- **SUCCESS:** HTTP **404** and body
  `{"error":"Event <UUID_B> is past the ai_events retention window and can no longer be evaluated"}`.
- **FAILURE:** 404 with the *not-found* message (classification inverted), 202, or 500.
- **NEITHER:** the seed precondition wasn't actually achieved (row not in `events`, or still
  in `ai_events` because the mutation hadn't finished) — re-establish the precondition and
  retry; do not record a verdict until `events≥1 ∧ ai_events=0` is confirmed.

> Note: B is the single most important assertion in this plan. A and B together prove the
> new two-way miss classification. If you can only run one group, run A+B.

### C. eval-runs — event present → 202 started  *(secondary; needs ai_events + Temporal)*

1. Capture an `$ai_generation` (§F) with `UUID_C` / `TARGET_TS`; poll until it is in
   `ai_events` (`SELECT count() ... = 1`).
2. POST eval-runs with `target_event_id=UUID_C`.

- **SUCCESS:** HTTP **202**, body has `"status":"started"` and a `workflow_id`.
- **FAILURE:** 404 (it should have found the event), or a malformed 202 body.
- **NEITHER:** HTTP **500** `{"error":"Failed to start evaluation"}` — most likely **Temporal
  is not running** (the lookup succeeded but workflow start failed). This does **not**
  validate or invalidate the resolver change; mark **BLOCKED (Temporal)** unless logs show a
  different cause. Also NEITHER if the capture row never lands (ingestion down → BLOCKED).

> The 202 only proves the lookup found the row in `ai_events`; it does not require the
> downstream workflow to *complete* (which would need an LLM provider key for non-`hog`
> evaluations). Assert the endpoint response, not the workflow result.

### D. Fallback read endpoints (`fall_back_to_events=True`)

These return `events` data on an `ai_events` miss instead of raising. Endpoints and their
nature differ — assert accordingly:

| Endpoint (project-scoped unless noted) | Fallback usefulness | SUCCESS shape |
|---|---|---|
| `llm_analytics/evaluation_summary` | useful w/o heavy cols (aggregates eval results) | 200 + plausible data |
| `llm_analytics/offline_evaluations` | useful w/o heavy cols | 200, no error |
| `llm_analytics/sentiment` | **degrades** (needs heavy `$ai_input`, stripped from events) | 200, no error, possibly empty |
| `llm_analytics/@me/spend` (root `/api/llm_analytics/@me/spend`, **conditionally registered**) | useful w/o heavy cols (costs) | 200 + spend numbers |

For each: read the viewset/serializer to learn required query params (date range, etc.) —
do not guess. Then:
```
curl -s -o /tmp/d.json -w "%{http_code}\n" \
  "http://localhost:8010/api/projects/<TEAM_ID>/llm_analytics/evaluation_summary?<params>" \
  -H "Authorization: Bearer phx_dev_local_test_api_key_1234567890abcdef"
```

- **SUCCESS:** HTTP **200** with no error key. For the heavy-independent endpoints, data
  consistent with what's in `events`; for `sentiment`, a graceful 200 (empty is acceptable —
  the heavy input is intentionally absent from `events`; flipping this path off fallback is a
  documented *deferred* follow-up, so degraded-but-not-erroring is the **expected** current
  state).
- **FAILURE:** HTTP **500** / an unhandled exception / a stack trace in the body. A raise
  escaping a `fall_back_to_events=True` path is a regression.
- **NEITHER:** 400 (param shape wrong — fix it), 404 (route not registered, e.g. personal
  spend behind its condition — note it), empty 200 on a heavy-independent endpoint where you
  *expected* data (ambiguous — see branch confirmation below before judging).

**Branch confirmation (optional but turns an ambiguous 200 into a real SUCCESS).** Confirm the
read actually took the fallback branch rather than finding ai_events data, via the query
tags the resolver sets (`ai_query_source`): inspect `system.query_log` right after the call:
```
python manage.py shell -c "from posthog.clickhouse.client import sync_execute; \
  print(sync_execute(\"SELECT log_comment FROM system.query_log WHERE event_time > now()-60 \
    AND log_comment LIKE '%ai_query_source%' ORDER BY event_time DESC LIMIT 5\"))"
```
Look for `dedicated_table` (served from ai_events), `shared_table_fallback` (fell back),
`expired`, or `not_found`. To force the fallback branch deterministically, run the endpoint
over a window where you seeded an `events`-only AI row (as in §B) and confirm
`shared_table_fallback` appears. If the query log isn't populated locally, record the 200 +
data as the evidence and note the branch is unconfirmed (→ INVESTIGATE, not SUCCESS).

### E. Trace read path (HogQL `ai_events` query runner)

`trace_query_runner.py` / `trace_neighbors_query_runner.py` read traces from `ai_events`.
Exercise via the query API. Construct the query payload from the runner/Query schema (read
the runner files and `products/ai_observability/frontend/.../useAIData.ts` for the exact
`kind` and params — do not guess the shape):
```
curl -s -X POST http://localhost:8010/api/environments/<TEAM_ID>/query/ \
  -H "Authorization: Bearer phx_dev_local_test_api_key_1234567890abcdef" \
  -H "Content-Type: application/json" \
  -d '{"query": { ...TracesQuery / trace query for the captured UUID_C... }}'
```

- **SUCCESS:** 200, and the trace for a recently-captured AI event includes the heavy
  `$ai_input` / `$ai_output` (proves it read `ai_events`, where the heavy data lives).
- **FAILURE:** 200 but heavy fields are empty for an event that *is* in `ai_events` (would
  imply it read the stripped `events` table); or 500.
- **NEITHER:** could not construct a valid query payload, or no trace data seeded → seed
  via capture (§F) first, else mark cannot-cover.

### F. Write-path split (capture → events stripped, ai_events full)  *(needs ingestion)*

First **prove ingestion populates `ai_events` at all** — if not, this whole group is BLOCKED.

Capture an `$ai_generation` with heavy + light props and a known UUID:
```
curl -s -X POST http://localhost:8010/i/v0/e/ \
  -H "Content-Type: application/json" \
  -d '{
        "api_key": "<PROJECT_TOKEN>",
        "event": "$ai_generation",
        "timestamp": "<TARGET_TS>",
        "uuid": "<UUID_F>",
        "distinct_id": "test-split-user",
        "properties": {
          "$ai_input": "HEAVY INPUT MARKER",
          "$ai_output": "HEAVY OUTPUT MARKER",
          "$ai_tools": ["a","b"],
          "$ai_model": "gpt-4",
          "$browser": "Chrome"
        }
      }'
```
(If `/i/v0/e/` is not the active capture path locally, the classic `POST /e/` /
`/capture/` with the same JSON works; confirm which one returns 200 and actually ingests.)

Poll both tables (ingestion is async — allow ~30–60s, poll, don't assume):
```
python manage.py shell -c "from posthog.clickhouse.client import sync_execute; \
  print('events', sync_execute(\"SELECT properties FROM events WHERE team_id=<TEAM_ID> AND uuid='<UUID_F>'\")); \
  print('ai_events', sync_execute(\"SELECT properties FROM ai_events WHERE team_id=<TEAM_ID> AND uuid='<UUID_F>'\"))"
```

- **SUCCESS (all three):**
  1. `events` row exists and its `properties` **omit** every heavy key
     (`$ai_input`, `$ai_output`, `$ai_output_choices`, `$ai_input_state`, `$ai_output_state`,
     `$ai_tools`) while **keeping** light ones (`$ai_model`, `$browser`).
  2. `ai_events` row exists and carries the heavy data (in `properties` and/or the native
     heavy columns — check `SHOW CREATE TABLE ai_events` for column names like the
     `$ai_input`/`$ai_output` equivalents).
  3. The light props are present in both.
- **FAILURE:** `events` row still contains heavy keys (split not stripping); **or** no
  `ai_events` row though `events` has one (split not duplicating); **or** `ai_events` row is
  missing the heavy data.
- **NEITHER:** neither row appears within the poll window → ingestion isn't writing AI
  events locally → **BLOCKED (cannot cover: ingestion not populating ai_events)**. Capture
  returning 200 only means it was accepted, not ingested — judge on the rows, not the POST.

### G. Eval scheduler (Kafka → Temporal) — **CANNOT COVER via this method**

The scheduler is a long-running Node consumer of the `clickhouse_ai_events_json` Kafka topic
that matches events against evaluation filters and starts Temporal workflows. It has no
synchronous API surface. Asserting its behaviour would require: the consumer running, a
configured matching evaluation, publishing/ingesting an `$ai_generation` that matches, and
then inspecting the Temporal UI / `system` for a started workflow and the consumer's
Prometheus counters (`evaluation_scheduler_events_processed`, `evaluation_matches`) — i.e.
orchestration well beyond direct API/DB probing, and inherently racy. **Document as not
covered.** If you want a *smoke* signal only (not a pass/fail): confirm the consumer process
is alive and, after a matching capture, that `evaluation_scheduler_messages_received`
increments — but treat that strictly as INVESTIGATE-grade evidence, never as SUCCESS for the
scheduler logic. The unconditional-split change (§F) is the prerequisite the scheduler now
relies on (the `ai_events` topic carries the unstripped payload); verifying §F is the
closest in-scope proxy.

### H. Frontend flag-gate removal — **CANNOT COVER (no browser)**

The change removed the `AI_EVENTS_TABLE_ROLLOUT` flag gate from the AI observability data
logics (`aiObservabilityAIDataLogic.ts`, `useAIData.ts`, `aiObservabilitySentimentLogic.ts`),
so the UI now always reads the `ai_events`-backed paths. Verifying the *rendered* behaviour
needs a browser, which is out of scope (no Playwright). The **API calls those logics make**
are the same endpoints covered in §D/§E, so the data layer is covered; the
rendering/flag-removal itself is **not covered here**. Document as such.

---

## 6. Cleanup

- Delete the `Evaluation` you created (`DELETE /api/projects/<TEAM_ID>/evaluations/<EVALUATION_ID>/`)
  or leave it — local only, your call, but note what you left behind.
- The captured/seeded ClickHouse rows are harmless test data on a local instance. If you want
  a clean slate, `ALTER TABLE sharded_events DELETE` / `sharded_ai_events DELETE` the UUIDs
  you used. Note any rows left behind.
- Do not commit this file or any seed artifacts to the branch.

---

## 7. Report format

Produce a table: **Surface (A–H) | Verdict (SUCCESS / FAILURE / INVESTIGATE / BLOCKED) |
Evidence (HTTP code + body excerpt, row counts, query-log tag)**. For every INVESTIGATE or
BLOCKED, state the precise reason and what would unblock it. Call out explicitly that G and H
are not coverable by this method and why. Do not summarize a run as "passing" unless A and B
are SUCCESS; those two are the load-bearing assertions for this change.
