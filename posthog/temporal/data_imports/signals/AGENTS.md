# Data import signals

Emits Signals from newly imported external data source records (Zendesk tickets, GitHub issues, etc.)
to surface actionable product feedback.

## How emitted signals are used

Each emitted signal is sent to the Signals workflow (`products/signals/backend/api.py:emit_signal`)
where its `description` is embedded for semantic search.
Signals from different sources and types are then combined into signal groups and processed into signal reports to help users find issues with their products.

This means the `description` field must be written for embedding quality:
it should capture the meaning of the record in a source-agnostic way
so that semantically similar signals group well regardless of origin.

## Architecture

The pipeline is a Temporal child workflow, fire-and-forget from the main import job:

1. **Parent workflow** (`posthog/temporal/data_imports/external_data_job.py`) finishes importing data,
   then spawns the emit-signals child workflow if emission is enabled for the source.
2. **Child workflow** (`posthog/temporal/data_imports/workflow_activities/emit_signals.py`) runs a single activity that:
   - Looks up the config from the registry for the given source type and schema
   - Queries new records via HogQL (filtered by partition field since last sync)
   - Runs each record through the source's **emitter function** to produce signal outputs
   - Optionally **summarizes long descriptions** via LLM if the config defines a `summarization_prompt` and `description_summarization_threshold`.
     Descriptions exceeding the threshold are summarized; if the summary is still too long, retries once with error context; truncates as last resort.
   - Optionally filters through an **LLM actionability check** if the config defines a prompt (runs after summarization)
   - Emits surviving outputs as Signals via `products/signals/backend/api/emit_signal`
3. **Registry** (`posthog/temporal/data_imports/signals/registry.py`) maps (source type, schema name) pairs to their config.
   All emitters are auto-registered at module load time.

Gated behind the `emit-data-import-signals` feature flag (`EMIT_SIGNALS_FEATURE_FLAG` in `posthog/temporal/data_imports/signals/registry.py`),
checked at the parent workflow level before spawning the child.

## Adding a new source

1. **Create the emitter module** — add a file in this directory (e.g., `jira_issues.py`).
   Follow existing emitters (`posthog/temporal/data_imports/signals/zendesk_tickets.py`,
   `posthog/temporal/data_imports/signals/github_issues.py`) for the pattern:
   define which fields to query,
   write a pure emitter function that transforms a record dict into a signal output (or `None` if data is insufficient),
   optionally define an LLM actionability prompt and/or a summarization prompt with threshold,
   and export the final config as a module-level constant.
2. **Register in `posthog/temporal/data_imports/signals/registry.py`** — import the config and add it inside `_register_all_emitters()`.
   The source type must match an `ExternalDataSourceType` enum value,
   and the schema name must match the table name as it appears in the data warehouse.
3. **Write tests in `posthog/temporal/data_imports/signals/tests/`** — emitter tests (`test_<source>.py`) covering valid records,
   missing/empty required fields (parameterized), and extra field extraction.
   Add a realistic mock record and pytest fixture in `posthog/temporal/data_imports/signals/tests/conftest.py`.

Run tests: `pytest posthog/temporal/data_imports/signals/tests/`

## Maintaining this file

If the pipeline architecture, registry pattern, or conventions change significantly,
update this AGENTS.md to reflect the new reality.
