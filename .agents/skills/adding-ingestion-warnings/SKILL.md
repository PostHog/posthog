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
[nodejs/src/ingestion/common/ingestion-warning-types.ts](../../../nodejs/src/ingestion/common/ingestion-warning-types.ts)
(a dependency-free leaf, re-exported from `ingestion-warnings.ts`, so codegen and its test can import it cheaply).
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

Rust services emit warnings through the `common-ingestion-warnings` crate ([rust/common/ingestion_warnings](../../../rust/common/ingestion_warnings)).
Unlike nodejs (which has database access and writes the v2 row directly), Rust producers have no token→team resolution, so they don't write the row themselves.
Instead they emit a synthetic `$$client_ingestion_warning` `CapturedEvent` onto the existing `client_ingestion_warning` topic; the nodejs `clientwarnings` consumer resolves the token to a `team_id`, reads the structured type/details/source, and writes the v2 row (see [handle-client-ingestion-warning-step.ts](../../../nodejs/src/ingestion/common/steps/event-processing/handle-client-ingestion-warning-step.ts)).

### The Rust `WarningType` is generated — nodejs is the single source of truth

There is no hand-maintained Rust copy of the type list. Entries in `INGESTION_WARNING_TYPES` flagged `captureProduced: true` are exactly the types Rust may emit, and a generator mirrors that set into a committed artifact the Rust build reads:

```text
INGESTION_WARNING_TYPES (captureProduced: true)              # nodejs — source of truth
  → pnpm --filter=@posthog/nodejs gen:ingestion-warning-types
  → rust/common/ingestion_warnings/capture_warning_types.generated.json   # committed
  → build.rs → WarningType enum + ALL + as_str()             # generated at build time
```

The artifact is committed _inside_ the Rust crate so the isolated Rust Docker/CI build context stays self-contained — no cross-workspace file reads. The same `captureProduced` flag also derives the `CAPTURE_PRODUCED_WARNING_TYPES` allowlist the consumer enforces, so a single edit wires a type on both sides. Two tests guard the chain: the nodejs no-drift test (`generate-ingestion-warning-types.test.ts`) fails if the committed artifact and the generator output diverge, and the Rust `from_tag_round_trips_every_registered_type` test fails if a generated variant has no `from_tag` arm.

To add a **capture-produced** type:

1. **Register it in nodejs** — add the type to `INGESTION_WARNING_TYPES` with `captureProduced: true` (see the nodejs steps above for `category`/`severity`, which the consumer owns). This also puts it on the `CAPTURE_PRODUCED_WARNING_TYPES` allowlist automatically.
2. **Regenerate + commit the artifact** — run `pnpm --filter=@posthog/nodejs gen:ingestion-warning-types` and commit the updated `capture_warning_types.generated.json`.
3. **Add the Rust `from_tag` arm** — in `src/registry.rs`, map the capture error tag (`v1::Error::tag()` / per-event drop detail) to the newly generated `WarningType` variant. The variant, `as_str`, and `ALL` are generated — never hand-write them. `from_tag` stays hand-written because it maps capture's error taxonomy onto the registry and is the allowlist that makes unregistered tags emit nothing; the round-trip test forces you to add the arm.

Emitting from Rust:

- **Emit it** via `WarningEmitter::emit(token, source, warning, details, count)` — the builder injects `count` and `pipelineStep` into details and stamps `type`/`source`/`details` into the event properties the consumer reads. Use the same camelCase details keys as nodejs (`distinctId`, `eventUuid`, ...). The envelope's top-level `distinct_id` is always the token (never the offending id), so an oversized offending distinct_id can't make the consumer drop the warning.
- **`source` identifies the producer** (`src/lib.rs`): a `WarningSource { service, path }`. `service` is the stable message `source` field and metric label (e.g. `"capture"`) — pick one per service, don't invent a new value per call site. `path` is metric-only, for splitting volume within one service's emit sites (e.g. `"v1_analytics"`); it never reaches the message. Capture's only source today is `CAPTURE_V1_ANALYTICS`.
- **Best-effort, fire-and-forget**: throttled per `(token, type)` per pod, never awaited, never fails the caller. Capture gates it behind `CAPTURE_INGESTION_WARNINGS_ENABLED` (default off; see `rust/capture/src/config.rs`). The producer is a `common-kafka` `ThreadedProducer` (built via `create_threaded_kafka_producer` with `observe_delivery` as its delivery callback, so delivered/failed outcomes are counted on the producer's own poll thread — no per-message task). It reuses the main event cluster's hosts/TLS and the `client_ingestion_warning` topic but runs on its own dedicated `KafkaConfig`: the fire-and-forget policy (`client.id=capture-ingestion-warnings`, `acks=1`, `retries=0`, `linger.ms=100`, a bounded 10k-message queue, a 5s message timeout) is fixed in code as the `WARNINGS_KAFKA_*` constants in `rust/capture/src/setup.rs` — not env-configurable — while only the two capacity/safety limits stay tunable via env (`CAPTURE_INGESTION_WARNINGS_KAFKA_QUEUE_MIB` and `..._MESSAGE_MAX_BYTES`). So a slow or saturated warnings topic can never contend with the main event producer.
- **Crate deps**: `common-ingestion-warnings` depends on `common-types` (for `CapturedEvent`) and `common-kafka` (the producer) — not on `capture` or any service crate. `WarningEmitter` is a plain trait object (`Arc<dyn WarningEmitter>`), so any Rust service can depend on the crate and wire it the way capture does in `router::State` / `setup.rs`; a team-aware service just supplies its own token.

## Rolling out a new capture-produced type

Adding a `captureProduced` type is an additive schema change, but nodejs and Rust capture deploy independently, so order matters:

- **Deploy the consumer (nodejs) before the producer (Rust capture).** The `clientwarnings` consumer must recognize the new type before capture emits it. If capture ships first, the consumer falls back to the generic `client_ingestion_warning` type for the unknown value (no crash — but the structured type/details are lost until nodejs catches up).
- Because the Rust enum is generated from the committed artifact, both changes normally land in the **same PR/commit** — but they still roll out as two separate deploys, so merging together doesn't guarantee simultaneous rollout. Treat nodejs-before-capture as the safe order.
- Capture is gated behind `CAPTURE_INGESTION_WARNINGS_ENABLED` (default off). On a brand-new producer path, keep it disabled until the consumer deploy carrying the new type is live, then enable.
- Removing a type is the reverse: stop emitting from capture first, then drop it from the nodejs registry (and regenerate) once no in-flight messages reference it.

## Downstream checklist

When adding a type, also update:

- **v1 UI map** — `WARNING_TYPE_TO_DESCRIPTION` (and `WARNING_TYPE_TO_DOCS_ANCHOR` if documented) in `frontend/src/scenes/data-management/ingestion-warnings/IngestionWarningsView.tsx`.
- **posthog.com docs** — the ingestion warnings page (`https://posthog.com/docs/data/ingestion-warnings`) if the warning is user-actionable.
- **v2 API / MCP descriptions** — only if you added a new category or severity value; the example vocabularies live in the `ingestion_warnings_v2` serializer help texts (`posthog/api/ingestion_warnings_v2.py`).

## Related

- Warning-fixing skills (`fixing-<warning-type>`) that teach agents how to resolve each warning are planned under the ingestion warnings v2 effort; authoring one per new warning type will become part of this checklist.
