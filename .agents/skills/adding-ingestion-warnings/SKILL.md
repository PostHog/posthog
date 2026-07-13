---
name: adding-ingestion-warnings
description: >
  How to add a new ingestion warning type to the event ingestion pipeline.
  Use when emitting a new warning from nodejs ingestion code (emitIngestionWarning, captureIngestionWarning, pipeline `warnings` arrays, `drop()` with warnings), when adding a warning type, category, or severity, or when a typecheck error says a string is not assignable to IngestionWarningType.
  Covers the INGESTION_WARNING_TYPES registry (the single source of truth for type, category, and severity), the details-key conventions that ClickHouse v2 materializes into columns, debouncing, and the downstream surfaces to keep in sync (v1 UI map, docs, v2 API).
---

# Adding ingestion warnings

Ingestion warnings tell customers their events were ingested with problems (or dropped).
They are produced to the `clickhouse_ingestion_warnings` Kafka topic and land in two ClickHouse tables: v1 (`ingestion_warnings`) and v2 (`ingestion_warnings_v2`, which materializes structured columns from the details JSON).

## The registry is the source of truth

Every warning type must be registered in `INGESTION_WARNING_TYPES` in
[nodejs/src/ingestion/common/ingestion-warnings.ts](../../../nodejs/src/ingestion/common/ingestion-warnings.ts).
The registry fixes the type's `category` and `severity`; they are resolved at serialization time, so callsites cannot drift or forget them.
An unregistered type is a compile error (`IngestionWarningType` is the registry's key union).

To add a new warning:

1. **Register the type** in `INGESTION_WARNING_TYPES`, inside the matching group comment block. Pick:
   - `category` — one of `size`, `merge`, `event`, `transformation`, `replay`. Extend `IngestionWarningCategory` only when the warning genuinely doesn't fit an existing group; new categories flow into API filters and agent-facing docs, so keep the vocabulary small.
   - `severity` — follow the convention: `error` = the event or message was dropped, `warning` = ingested but modified or partially rejected, `info` = informational or an intentional, team-configured drop.
2. **Emit it** (see below), passing only per-occurrence fields: `details`, `pipelineStep`, optional `key` / `alwaysSend`.
3. **Update downstream surfaces** (see checklist).

## Emitting

Two paths, both end at `serializeIngestionWarning`:

- **Pipeline steps** (preferred): return warnings on the result — `ok(value, sideEffects, warnings)` or `drop(reason, [], warnings)`. They accumulate in `context.warnings` and are sent by `handleIngestionWarnings()`, which requires a `teamAware()` block. See the framework doc test [09-ingestion-warnings](../../../nodejs/src/ingestion/framework/docs/09-ingestion-warnings.test.ts).
- **Direct emit**: `emitIngestionWarning(outputs, teamId, warning)` (outputs-based, preferred) or `captureIngestionWarning(kafkaProducer, teamId, warning)` (legacy) for code outside the pipeline result flow.

### Details keys ClickHouse v2 materializes

`ingestion_warnings_v2` derives columns from these exact JSON key names (see `posthog/models/ingestion_warnings/sql_v2.py`) — use them, don't invent variants:

| details key  | v2 column     |
| ------------ | ------------- |
| `eventUuid`  | `event_uuid`  |
| `distinctId` | `distinct_id` |
| `personId`   | `person_id`   |
| `groupKey`   | `group_key`   |

`category`, `severity`, and `pipelineStep` are appended to details by the serializer — never set them in `details` yourself; a stray key cannot override them (structured fields are spread last).

### Debouncing

Warnings are rate-limited per `team:type:key`. Set `key` to the entity you want to debounce by (e.g. a distinct ID) and `alwaysSend: true` only for warnings that must never be dropped by the limiter.

## Rust

No Rust service emits ingestion warnings today — the Rust capture service only routes `$$client_ingestion_warning` events to Kafka; the nodejs pipeline turns them into warnings.
If a Rust service ever needs to produce to `clickhouse_ingestion_warnings` directly, mirror the nodejs registry in a Rust module (type enum with `category()` / `severity()`), keep the JSON shape identical to `serializeIngestionWarning`, and update this skill to point at it.

## Downstream checklist

When adding a type, also update:

- **v1 UI map** — `WARNING_TYPE_TO_DESCRIPTION` (and `WARNING_TYPE_TO_DOCS_ANCHOR` if documented) in `frontend/src/scenes/data-management/ingestion-warnings/IngestionWarningsView.tsx`.
- **posthog.com docs** — the ingestion warnings page (`https://posthog.com/docs/data/ingestion-warnings`) if the warning is user-actionable.
- **v2 API / MCP descriptions** — only if you added a new category or severity value; the example vocabularies live in the `ingestion_warnings_v2` serializer help texts (`posthog/api/ingestion_warnings_v2.py`).

## Related

- Warning-fixing skills (`fixing-<warning-type>`) that teach agents how to resolve each warning are planned under the ingestion warnings v2 effort; authoring one per new warning type will become part of this checklist.
