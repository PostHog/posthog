---
name: adding-inbox-sources
description: Add a data warehouse table as a Self-driving Inbox signal source (the feature that ships GitHub, Linear, Zendesk, Jira, PagerDuty, Sentry, Snyk, Canny and others). A source syncs one warehouse table of actionable records (issues, tickets, conversations, incidents, findings, feedback, reviews) and the signals pipeline turns new rows into signals. Use when asked to "add a new inbox/self-driving source", "make <vendor> a signal source", or to find which warehouse sources could become signal sources. Covers candidate discovery, the backend emitter and registry, the signals frontend source catalog, the optional context-mill wizard entry, and created_via attribution.
---

# Adding a Self-driving Inbox source

The Self-driving Inbox connects a PostHog **data warehouse source** and syncs one table of actionable records.
After each sync, the signals pipeline reads the new rows, filters them with an LLM actionability gate, and emits signals.
The pipeline is driven by a static registry keyed on `(ExternalDataSourceType, table)`, so each table needs an emitter config.

All work happens in this repository:

| Surface             | What changes                                                                                            |
| ------------------- | ------------------------------------------------------------------------------------------------------- |
| Backend (required)  | `SignalSourceProduct` value, emitter module, registry entry, contract variant, a test row               |
| Frontend (required) | `products/signals/frontend/inbox/externalSignalSources.ts` entry and the `signalSourcesLogic.ts` unions |
| Wizard (optional)   | `PostHog/context-mill` `self-driving` skill, so `npx @posthog/wizard self-driving` offers the source    |

Do **not** edit the desktop app (`products/desktop/`) or `packages/agent/packages/agent-contracts/src/inbox-types.ts` for a new source.
A desktop change in the same PR as a new `SignalSourceProduct` value fails the desktop/backend coupling check, and the inbox does not need it.

The data warehouse source itself must already exist and be implemented.

## Find candidates

1. List implemented sources: iterate `SourceRegistry.get_all_sources()` and keep a source when `type(src).get_schemas is not _BaseSource.get_schemas` and `get_source_config.unreleasedSource` is false.
   Run it on a fresh `origin/master` worktree.
2. Call `get_documented_tables()` for each source. It gives table names and incremental fields without credentials.
   `get_canonical_descriptions()` gives column names.
3. Keep tables that hold one actionable record per row: issues, tickets, conversations, incidents, alerts, findings, feedback, reviews, survey responses.
   Skip CRM tasks and notes, message logs, blog posts and event tickets.
4. Check that each table has a human-readable text column, a stable id, and a creation timestamp.
   Tables with text only in nested JSON need a bespoke emitter. Tables with one row per occurrence need grouping (see below).
5. Compare against `_register_all_emitters()` in `products/signals/backend/emission/registry.py` and open PRs (`gh pr list --search "inbox source in:title"`).

## Backend checklist (per source)

Code lives in `products/signals/backend/`. Read `emission/CLAUDE.md` first.

1. **Enum**: add a `SignalSourceProduct` value and a `SIGNAL_SOURCE_PRODUCT_LABELS` entry in `enums.py`.
   The model's choices are callables, so a new value needs **no migration**.
   A new record kind needs a `SignalSourceType` value, the matching `models.py` `SourceType` choice, and a prompt pair in `emission/_prompts.py`.
2. **Emitter**: add `emission/<product>_<table>.py` exporting a `SignalSourceTableConfig`.
   - Flat tables use `make_flat_emitter` from `emission/_common.py` (see `pagerduty_incidents.py`).
   - Nested JSON: extract in HogQL with `JSONExtractString(col, 'key') AS new_alias`, using an alias that differs from the column name, or parse in Python (see `jira_issues.py`, `intercom_conversations.py`, `emission/_survey.py`).
   - Warehouse columns are **snake_case**. The import renames API fields (`createdAt` becomes `created_at`). Check the source's `canonical_descriptions.py` and `settings.py`.
   - `partition_field` is the creation timestamp. Set `partition_field_is_datetime_string=True` for string columns. The fetcher wraps the column in `parseDateTimeBestEffort(toString(...))`, so a native timestamp also works. Epoch columns use an expression such as `fromUnixTimestamp(intDiv(toInt(col), 1000))`.
   - Tables with one row per occurrence (no grouped issue id) use `fetchers/grouped_warehouse.py` with a `GROUP BY`, so one issue emits once instead of flooding the inbox.
   - Use `where_clause` to skip resolved, closed or empty-text rows only when the status values are certain. A filter on a column that a vendor sometimes omits makes the whole query fail.
   - Do not select PII (emails, names, user objects, IPs). Use ids, urls, statuses and severities.
   - Reuse the shared prompt pair for the record kind. Siblings use `max_records=200`, `first_sync_lookback_days=1` and `description_summarization_threshold_chars=2000`.
3. **Register**: `register_signal_source(ExternalDataSourceType.X, "<table>", CONFIG)` in `_register_all_emitters()`. The table name must match the schema name the source returns, including casing (`Issues`, `Cases`).
4. **Contract**: in `contracts.py` add `<Name><Kind>SignalExtra` (one `str | None` per extra field, `list` for list fields) and `<Name><Kind>SignalInput`, then add the Input to the `SignalInput` union and the `SIGNAL_INPUT_VARIANTS` tuple.
5. **Tests**: add a row to `TIER1_SOURCES` in `emission/tests/test_tier1_registry.py`. It checks registration, the contract and the prompts. A bespoke emitter also gets a small parameterized test file for its parsing edge cases.
6. **Generated types**: a new enum value changes `products/signals/frontend/generated/` and the MCP generated files. Run `hogli build:openapi`, or let the CI bot commit the regenerated types to the branch.

Check that the fetch query parses: build the SELECT the fetcher builds and run `parse_select` from `posthog.hogql.parser` on it.

## Frontend checklist (per source)

1. `products/signals/frontend/inbox/externalSignalSources.ts`: add an `EXTERNAL_SIGNAL_SOURCES` entry with `source`, `label`, `category`, `watches`, `dwSourceType` (the exact `ExternalDataSourceType` string), `requiredTables` and `sourceType` (the record kind).
   Write `watches` in sentence case and follow `/writing-user-facing-copy`.
   `WAREHOUSE_SOURCE_SETUP` derives from this list, so it needs no edit.
2. `products/signals/frontend/inbox/signalSourcesLogic.ts`: add the product to **every** hand-written `externalSourceStates: Record<...>` union, in alphabetical order.
   There are several, and they must all equal the `EXTERNAL_SIGNAL_SOURCES` list.

## The self-driving wizard (`PostHog/context-mill`), optional

The wizard's connected-tools list is hardcoded, so a new source is not offered during `npx @posthog/wizard self-driving` until you add it.
Edit `context/skills/self-driving/references/5-connected-tools.md` (plus the source lists in `4-sources.md`, `2-read-context.md` and `description.md`):

1. Add the tool to the step-5 `wizard_ask` options.
2. Add its responder mapping: the same `source_product` and record kind as the emitter.
3. Add its warehouse `source_type` to the "already connected" detection list.
4. Credential sources are recorded as a follow-up, with no connector file. One-click OAuth sources get a connector reference (clone `5b-linear.md`).

Run `node scripts/build.js` once to confirm the skill bundles.

## created_via attribution

`ExternalDataSource.created_via` is set server-side from the request transport (`get_event_source` in `posthog/event_usage.py`).
Callers cannot set it, and a new source needs no wiring.
The upgrade from `mcp` to `self_driving` lives in `_create_external_data_source` in `products/warehouse_sources/backend/presentation/views/external_data_source.py`.

## PR conventions

- Title: `feat(data-warehouse): add <Source or group> as self-driving inbox sources`.
- Group related sources (incidents, security, trackers, support, feedback) in one PR per group.
- PRs that edit the same lists (`registry.py`, `contracts.py`, `test_tier1_registry.py`, `externalSignalSources.ts`, `signalSourcesLogic.ts`) conflict with each other after one merges. Keep the entries from both sides when you resolve the conflict, and keep every `signalSourcesLogic.ts` union complete.

## Gotchas

- `source_type` on the warehouse source (`"Jira"`), `source_product` (`"jira"`) and the record kind (`"issue"`) are three different fields.
- `dwSourceType` must equal the real `ExternalDataSourceType` string.
- A column the vendor omits for some accounts (`priority`, `date_closed`, `archived_at`) may be missing from the synced table. Do not select or filter on it unless it is always present.
- Every canonical actionability prompt keeps the `When in doubt, classify as ACTIONABLE` line, because steering injection anchors on it.
