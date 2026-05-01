# Signal emission pipeline

Emits Signals from various sources — both external data imports (Zendesk tickets, GitHub issues, etc.)
and internal products (Conversations tickets) — to surface actionable product feedback.

## How emitted signals are used

Each emitted signal is sent to the Signals workflow (`products/signals/backend/api.py:emit_signal`)
where its `description` is embedded for semantic search.
Signals from different sources and types are then combined into signal groups and processed into signal reports to help users find issues with their products.

This means the `description` field must be written for embedding quality:
it should capture the meaning of the record in a source-agnostic way
so that semantically similar signals group well regardless of origin.

## Architecture

### Shared pipeline

The core signal pipeline (`posthog/temporal/data_imports/signals/pipeline.py`) is source-agnostic:

1. **Record fetcher** — each source defines a `record_fetcher` callable on its config
2. **Emitter** — transforms each record dict into a `SignalEmitterOutput` (or `None` to skip)
3. **Summarization** — optionally summarizes long descriptions via LLM
4. **Actionability filter** — optionally filters non-actionable records via LLM
5. **Emission** — emits surviving outputs as Signals via `products/signals/backend/api/emit_signal`

### Registry

`posthog/temporal/data_imports/signals/registry.py` maps `(source_type, schema_name)` pairs to their config.
All emitters are auto-registered at module load time.
The registry key is a plain string pair — external sources use `ExternalDataSourceType` values (e.g., `"Zendesk"`),
internal sources use their own identifiers (e.g., `"conversations"`).

### Record fetchers

Each source defines how to fetch records via its `record_fetcher` on the config:

- **Data warehouse fetcher** (`fetchers/data_warehouse.py`) — queries HogQL on warehouse tables.
  Receives `table_name` and `last_synced_at` via the runtime context dict.
- **Conversations fetcher** (`fetchers/conversations.py`) — queries Django ORM for Postgres tickets + comments.
  Records emission in `SignalEmissionRecord` optimistically at fetch time.

### Data import sources (Zendesk, GitHub, Linear)

Triggered by the data import workflow:

1. **Parent workflow** (`posthog/temporal/data_imports/external_data_job.py`) finishes importing data,
   then spawns the emit-signals child workflow if emission is enabled for the source.
2. **Child workflow** (`posthog/temporal/data_imports/workflow_activities/emit_signals.py`) runs the activity that
   calls `config.record_fetcher` then the shared pipeline.

### Conversations source

Triggered by a Temporal schedule (hourly):

1. **Coordinator workflow** (`conversations_coordinator.py`) queries teams with conversations signals enabled
   and spawns per-team child workflows (batched, ~50 concurrent).
2. **Per-team workflow** runs the activity that fetches eligible tickets (>1 hour old, not resolved,
   not yet emitted) with their full message threads, then runs the shared pipeline.

### Gating

All sources are gated behind AI consent (`organization.is_ai_data_processing_approved`)
and a `SignalSourceConfig` row with `enabled=True` for the matching `source_product`/`source_type`.
Users enable sources via the Inbox Sources modal.

## Adding a new source

1. **Create the emitter module** — add a file in this directory (e.g., `jira_issues.py`).
   Follow existing emitters (`zendesk_tickets.py`, `github_issues.py`, `conversations_tickets.py`) for the pattern:
   define which fields to query,
   write a pure emitter function that transforms a record dict into a signal output (or `None` if data is insufficient),
   define a `record_fetcher` (use `data_warehouse_record_fetcher` for warehouse sources, or write a new fetcher for other sources),
   optionally define an LLM actionability prompt and/or a summarization prompt with threshold,
   and export the final config as a module-level constant.
   **Avoid querying PII fields** (user IDs, email addresses, names, organization IDs, etc.)
   unless they are strictly required to locate the entity in the source system later.
   Prefer opaque record IDs and URLs over fields that identify people or organizations.
2. **Register in `registry.py`** — import the config and add it inside `_register_all_emitters()`.
   For external sources, use the `ExternalDataSourceType` value as the source type.
   For internal sources, use a descriptive string identifier.
3. **Write tests in `tests/`** — emitter tests (`test_<source>.py`) covering valid records,
   missing/empty required fields (parameterized), and extra field extraction.
   Add a realistic mock record and pytest fixture in `tests/conftest.py`.

Run tests: `pytest posthog/temporal/data_imports/signals/tests/`

## Local testing with fixtures

To exercise the full pipeline (emitter → summarization → actionability → `emit_signal`)
without running a real data import or populating a warehouse table,
use the `emit_signals_from_fixture` management command.
It loads sanitized fixture records from `products/signals/eval/fixtures/`
and feeds them straight into `run_signal_pipeline`,
bypassing `data_warehouse_record_fetcher` entirely.

```bash
# Smoke test with 1-2 records (cheap, ~1-2 LLM calls per record)
DEBUG=1 ./manage.py emit_signals_from_fixture --type zendesk --team-id 1 --limit 1
DEBUG=1 ./manage.py emit_signals_from_fixture --type github --team-id 1 --limit 2
DEBUG=1 ./manage.py emit_signals_from_fixture --type linear --team-id 1
DEBUG=1 ./manage.py emit_signals_from_fixture --type conversations --team-id 1 --limit 2

# Override the fixture path
DEBUG=1 ./manage.py emit_signals_from_fixture --type zendesk --team-id 1 --fixture path/to/custom.json
```

`--type` accepts `zendesk`, `github`, `linear`, or `conversations`
and maps to the matching auto-registered config in `registry.py`.
The command requires `DEBUG=True` and is intended for local iteration only.

## Maintaining this file

If the pipeline architecture, registry pattern, or conventions change significantly,
update this AGENTS.md to reflect the new reality.
