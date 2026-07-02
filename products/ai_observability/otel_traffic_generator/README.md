# OTel AI observability traffic generator

A standalone tool that sends synthetic LLM-analytics traffic through the AI
OpenTelemetry ingestion endpoint (`POST /i/v0/ai/otel`) and verifies it lands
correctly via the PostHog Django API. Built to validate AI ingestion against a
real environment (including prod) using only project-scoped credentials.

It follows a **plan → run → verify → compare** flow so the exact same traffic
can be replayed deterministically and results compared across runs — e.g. before
and after a change to the ingestion pipeline (the `AI_SINK_MODE` primary →
secondary cutover).

## Why plan-first

A `plan` is a pure, reviewable JSON artifact describing every trace, span, and
attribute to send, plus the expectations to assert after ingestion. It carries
no wall-clock time and no concrete span IDs — those are derived at `run` time
from `(plan_id, run_id)`. Consequences:

- `plan --seed N` is **byte-stable**: same inputs, same `plan_id`, same bytes.
- A `run` with a fixed `--run-id` and `--base-time` sends **byte-identical**
  requests every time (idempotent replay).
- A `run` with a fresh `--run-id` is **independently scoped** — its events never
  collide with a previous run's — so two runs can be verified and compared
  cleanly.

## Credentials

| Phase           | Credential                             | Notes                                                                                                   |
| --------------- | -------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `run` (ingest)  | Public project token `phc_…`           | `--token` / `POSTHOG_OTEL_TOKEN`. Sent as `Authorization: Bearer`.                                      |
| `verify` (read) | **Personal API key** with `query:read` | `--api-key` / `POSTHOG_PERSONAL_API_KEY`, plus `--project-id` / `POSTHOG_PROJECT_ID` (numeric team id). |

Note: the `/query` and `/events` endpoints do **not** accept a project secret
API key (`phs_`) today — there is no `query` scope available to project secret
keys — so verification uses a personal API key. Ingestion is project-token only.

## Running

Needs `requests` and `opentelemetry-proto` (both already in the repo's flox
venv, so from a checkout you can usually run with no install). Run as a module
from the repo root:

```bash
# 1. Build a deterministic plan
python -m products.ai_observability.otel_traffic_generator plan \
    --seed 42 --out plan.json

# 2. Send it (public project token). Writes run-<run_id>.json.
POSTHOG_OTEL_TOKEN=phc_xxx \
python -m products.ai_observability.otel_traffic_generator run \
    --plan plan.json --cloud us

# 3. Verify ingestion (personal API key with query:read + project id)
POSTHOG_PERSONAL_API_KEY=phx_xxx POSTHOG_PROJECT_ID=12345 \
python -m products.ai_observability.otel_traffic_generator verify \
    --plan plan.json --run run-<run_id>.json --cloud us
```

`run --verify` chains send + verify in one step. `run --dry-run` builds and
summarizes the OTLP requests without sending. `--cloud` picks host presets
(`us`, `eu`, `local`); override with `--capture-host` / `--api-host`.

## Comparing a pipeline change (primary vs secondary sink)

```bash
python -m ...otel_traffic_generator plan --seed 42 --out plan.json

# Baseline: AI_SINK_MODE=primary
python -m ...otel_traffic_generator run --plan plan.json --run-id baseline --verify \
    --result-out result-baseline.json

# ... flip AI_SINK_MODE to secondary, redeploy capture-ai ...

# Candidate: same plan, fresh scope
python -m ...otel_traffic_generator run --plan plan.json --run-id secondary --verify \
    --result-out result-secondary.json

# Diff the run-independent surface (event totals, tokens, cost, models, checks)
python -m ...otel_traffic_generator compare \
    --baseline result-baseline.json --candidate result-secondary.json
```

Because the plan is identical and costs are deterministic from model + tokens, a
healthy cutover yields `MATCH`. Any diff is attributable to the pipeline change.

## Coverage

The default plan exercises a broad, realistic slice of the ingestion + AI
observability surface:

- **Event types:** `$ai_generation`, `$ai_embedding`, `$ai_span`, and root spans
  promoted to `$ai_trace`.
- **SDK namespaces:** generic `gen_ai.*` (OpenAI-style), Vercel AI (`ai.*`),
  Traceloop/OpenLLMetry (`llm.request.type`), Pydantic AI (`pydantic_ai.*`).
- **Attribute mapping:** model, provider, input/output tokens, prompt/completion
  messages, cache-read/creation tokens, `server.address`, SDK name/version.
- **Derived properties:** cost from model + tokens, latency from span timestamps,
  `$ai_ingestion_source=otel`, trace/span/parent id linkage.
- **Scenarios:** single chat, multi-turn, RAG (embedding + generation), tool
  calls, error status (`$ai_is_error`), Anthropic cache tokens, multi-provider
  and multi-user distinct ids.

Scale volume with `--multiplier N` (repeats each scenario as N distinct users).
Narrow with `--scenarios openai_chat,rag_embedding`.

## Files

- `plan.py` — plan model + scenario catalog + deterministic build/hash.
- `send.py` — resolve a plan into OTLP protobuf and POST it; run receipt.
- `verify.py` — query the API (HogQL + `TracesQuery`/`TraceQuery`), build a
  normalized result, and diff two results.
- `cli.py` — argparse entry point.
- `test_generator.py` — determinism + OTLP-shape tests (no network).
