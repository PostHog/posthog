# Cymbal v2 processing API

## Product and design goal

Introduce a parallel Cymbal v2 processing API for the Node.js error-tracking consumer to use in a later migration.
The v2 API should be exposed through gRPC as a bidirectional stream: callers stream exception events into Cymbal and Cymbal streams one correlated outcome per item as soon as each item finishes.

The API should make per-item outcomes explicit instead of overloading the current HTTP `/process` behavior, where success is an ordered array of processed events and `null` means suppression.
The target contract is easier for callers to reason about under partial failure, supports lower-latency item completion, avoids large unary request/response payloads, and lets gRPC flow control provide natural backpressure.

## Non-goals

- Do not change Node.js ingestion behavior in this phase.
- Do not remove or change the existing HTTP `POST /process` contract.
- Do not change the already-defined canonical processed event schema.
- Do not expose Cymbal's internal remote-resolution API as the Node-facing contract.
- Do not add Django, ClickHouse, frontend, or MCP changes for this API-only phase.

## Current-state observations from the repo

- `rust/cymbal/README.md` describes Cymbal as the owner of HTTP ingress and the full error-tracking processing pipeline.
- `rust/cymbal/src/router/mod.rs` currently exposes HTTP `POST /process` plus health routes through Axum.
- `rust/cymbal/src/router/event.rs` accepts `Vec<AnyEvent>` and returns `Batch<Option<AnyEvent>>`.
  - Non-null entries are the processed `AnyEvent` with updated properties.
  - `None` entries represent suppressed events.
  - Unhandled failures and request backpressure are represented at the HTTP request level.
- `rust/cymbal/src/stages/http_pipeline.rs` adapts `AnyEvent` into the exception pipeline and converts handled errors back into either a processed event, a dropped event, or an event with attached error text.
- `rust/cymbal/src/stages/pipeline.rs` runs resolution, grouping, linking, and alerting over exception properties.
- `rust/cymbal/docs/compatibility.md` explicitly says Node currently uses HTTP `/process`, chunks by estimated body size, and receives `(CymbalResponse | null)[]` in input order.
- `proto/cymbal/resolution/v1/resolution.proto` already demonstrates a bidirectional gRPC stream pattern for internal remote symbol resolution, including per-stream item IDs, independent outcomes, and generated Rust bindings through `rust/cymbal-proto`.
- `rust/cymbal-resolution` shows an existing tonic server implementation pattern with metrics, load shedding, auth interception, health/readiness, and per-item stream handling.

## Proposed architecture

### Public v2 gRPC surface

Add a new public Cymbal processing proto package, conceptually separate from `cymbal.resolution.v1`, for example:

```text
package cymbal.process.v2
service CymbalProcess {
  rpc Process(stream ProcessItem) returns (stream ProcessOutcome)
}
```

This is the gRPC equivalent of the requested `v2/process` operation.
The exact proto package and service names can be adjusted to repo conventions, but the contract should remain clearly Node-facing and v2-specific.

### Stream model

Use a bidirectional stream of independent items:

- The client sends `ProcessItem` messages.
- Cymbal processes items independently, with bounded concurrency.
- Cymbal emits `ProcessOutcome` messages as items complete.
- Outcomes may arrive out of input order.
- Every accepted item gets exactly one terminal outcome.
- The stream stays open across many items until either side closes or a protocol/transport-level error occurs.

### Correlation model

Every `ProcessItem` must include a caller-provided correlation ID.
Every `ProcessOutcome` must echo the same caller correlation ID.

Caller-provided IDs are not required to be unique, even while multiple items with the same caller ID are in flight.
When Cymbal receives an item, it should allocate a server-side unique processing ID for internal bookkeeping, metrics, cancellation, and in-flight tracking.
The server-side ID is the authoritative internal key; the caller ID is an opaque value echoed back in the final outcome.

This means the protocol allows:

```text
client -> caller_id = 1
client -> caller_id = 1
server -> outcome caller_id = 1
server -> outcome caller_id = 1
```

If a caller needs unambiguous response matching for duplicate concurrent items, it should choose unique caller IDs.
Cymbal should not rely on caller ID uniqueness for correctness.

### Outcome model

Use three top-level terminal outcomes:

```text
done
drop
error
```

#### `done`

Means the item was valid and fully processed.
It includes the canonical processed event.
The returned event is authoritative for downstream callers.

#### `drop`

Means the item was valid enough to understand, and Cymbal intentionally decided it should not continue.
It includes a machine-readable drop code/reason.
It does not include retry fields.
Callers should not retry dropped items.

This should cover product or processing decisions such as suppression or intentional discard.
It should not be used for malformed input.

#### `error`

Means the item failed to produce a canonical processed event.
It includes:

- error kind/category
- strongly typed machine-readable error code enum
- explicit `retryable` boolean
- optional retry-after hint
- optional debug-safe message/details

Invalid payloads are represented as non-retryable errors:

```text
error.kind = invalid
error.retryable = false
```

Retryability exists only on `error`, not on `done` or `drop`.

### Error taxonomy direction

Keep the taxonomy small and caller-oriented at first.
Suggested conceptual kinds:

- `invalid`: payload or envelope violates the v2 contract; never retry unchanged input.
- `processing`: Cymbal failed while processing a valid item.
- `timeout`: item exceeded its processing budget.
- `dependency`: a required dependency was unavailable or failed.
- `internal`: unexpected Cymbal failure.

Implementation should use proto enums for error codes so generated Node.js types enforce the allowed values.
Messages and details are for logs/debugging, not control flow.

### Batch semantics

The protocol should not require a batch envelope.
A caller can send a batch as many streamed items and collect outcomes until it has one per input item.
This keeps batch grouping on the caller side and lets Cymbal stream early outcomes instead of waiting for the slowest item.

If future callers need batch boundaries for observability, they can add a batch ID or metadata field later without changing the core per-item outcome model.

### Relationship to existing HTTP `/process`

Keep HTTP `/process` as the compatibility surface for current Node ingestion.
Build v2 as a parallel gRPC API inside Cymbal.
The current HTTP behavior can either keep using `HttpEventPipeline` directly or, later, be adapted internally to the same v2 processing core if that reduces duplication.
Do not force that internal refactor in the first implementation unless it is the simplest safe path.

### Code organization direction

Likely areas to explore during implementation:

- `proto/cymbal/process/v2/process.proto`: new Node-facing processing contract.
- `rust/cymbal-proto/build.rs`: include the new proto for Rust binding generation.
- `rust/cymbal-proto/tests/`: add contract tests for item/outcome round trips and enum stability.
- `rust/cymbal/src/service/` or similar: add the tonic service implementation for v2 processing.
- `rust/cymbal/src/stages/`: add a processing adapter that can convert pipeline results into `done`, `drop`, and `error` outcomes without changing HTTP `/process` semantics.
- `rust/cymbal/src/main.rs` or the relevant binary startup path: run the gRPC server alongside the existing HTTP server if Cymbal currently only serves Axum.
- `rust/cymbal/src/config.rs`: add gRPC bind/config, stream concurrency, server-configured item deadline, and optional max in-flight-item controls.
- `rust/cymbal/src/metric_consts.rs`: add v2 stream/item metrics.
- `rust/cymbal/README.md` and `rust/cymbal/docs/compatibility.md`: document the parallel v2 API and clarify that Node remains on HTTP until a later migration.

Use the existing `cymbal.resolution.v1` proto and `rust/cymbal-resolution` service as implementation references, not as a contract to copy wholesale.
The v2 process API is Node-facing and processes whole canonical events, while resolution v1 is internal and processes exception-level symbol-resolution items.

## Implementation strategy

### Phase 1: Contract and documentation

- Define the v2 proto with bidirectional `Process` streaming.
- Model `ProcessItem` with a caller-provided correlation ID and the already-strict canonical input event payload shape.
- Model `ProcessOutcome` as a oneof with `Done`, `Drop`, and `Error` terminal variants.
- Add error kind/code/retry fields in a way that makes invalid payloads non-retryable errors.
- Document in proto comments:
  - out-of-order outcomes are allowed
  - each accepted item gets one terminal outcome
  - caller correlation IDs are opaque and may be duplicated
  - stream-level errors are reserved for protocol/transport failures
- Add proto contract tests.

### Phase 2: Cymbal gRPC server skeleton

- Add a Cymbal process service implementation using tonic.
- Start the gRPC server in parallel with existing HTTP serving.
- Add configuration for the v2 gRPC bind address and basic concurrency/load-shed limits.
- Use the same authentication model as the current HTTP Cymbal endpoint for the Node-facing boundary.
- Keep readiness/liveness behavior compatible with existing local and production entry points.
- Add metrics for streams opened/closed, items received, terminal outcomes by type/kind/code, item duration, and in-flight item count.

### Phase 3: Pipeline adapter

- Create a v2 adapter around the existing exception processing pipeline.
- Convert successful pipeline output into `done` with the canonical processed event.
- Convert suppression or intentional discard decisions into `drop` with enum reason codes, initially including `suppressed_issue` and `suppression_rule`.
- Convert malformed input into `error(kind=invalid, retryable=false)`.
- Convert runtime processing failures into `error` with enum error codes, explicit retryability, and optional retry-after.
- Keep the existing HTTP adapter behavior unchanged.

### Phase 4: Stream semantics and hardening

- Generate and track server-side unique processing IDs per stream.
- Allow duplicate caller correlation IDs; never use caller IDs as internal in-flight keys.
- Bound per-stream and process-wide in-flight items to avoid unbounded memory growth.
- Ensure cancellation and client disconnects release in-flight accounting.
- Prefer item-level `error` outcomes when Cymbal can identify the item and meaningfully classify the failure.
- Reserve stream termination for protocol violations, transport failures, server shutdown, or cases where the per-item contract cannot be maintained.

### Phase 5: Compatibility and future Node migration preparation

- Update Cymbal docs to explain that HTTP `/process` remains the active Node contract.
- Add compatibility notes for a future Node gRPC client migration:
  - callers may provide duplicate correlation IDs, but unique IDs are recommended when they need unambiguous matching
  - callers must consume outcomes out of order and use the echoed caller correlation ID as their routing hint; callers that need one-to-one matching should send unique IDs
  - callers should route `done`, `drop`, and `error` separately
  - callers should honor `error.retryable` and retry-after hints
- Do not add or change Node ingestion code in this plan.

## Validation and quality gates

Run commands through flox for Cymbal-side work:

```bash
flox activate -- bash -c "cd rust/cymbal && cargo fmt --check"
flox activate -- bash -c "cd rust/cymbal && cargo clippy --all-targets --all-features -- -D warnings"
flox activate -- bash -c "cd rust/cymbal && cargo test"
flox activate -- bash -c "cargo test -p cymbal-proto"
```

Also run targeted tests for any touched workspace crates, especially `cymbal-resolution` if shared proto generation or common gRPC setup changes affect it.
Before opening a PR, make sure formatter, clippy, tests, and shear do not raise errors.

Suggested test coverage:

- Proto contract round trips for `ProcessItem`, `ProcessOutcome`, outcome variants, and error enums.
- Stream accepts independent items and returns one outcome per accepted item.
- Outcomes can arrive out of order while preserving ID correlation.
- `done` includes the canonical processed event.
- Suppression/intentional discard maps to `drop`.
- Invalid payload maps to non-retryable `error(kind=invalid)`.
- Retryable processing failures include enum error codes and explicit retry hints when available.
- Duplicate caller correlation IDs are allowed and do not break internal processing because Cymbal uses server-generated processing IDs.
- Stream/client cancellation releases in-flight state.
- HTTP `/process` behavior remains unchanged.

## Agent handoff and exploration notes

Start implementation agents with these files:

- `rust/cymbal/README.md`
- `rust/cymbal/docs/compatibility.md`
- `rust/cymbal/src/router/event.rs`
- `rust/cymbal/src/stages/http_pipeline.rs`
- `rust/cymbal/src/stages/pipeline.rs`
- `proto/cymbal/resolution/v1/resolution.proto`
- `rust/cymbal-resolution/src/service/resolve.rs`
- `rust/cymbal-resolution/src/main.rs`
- `rust/cymbal-proto/README.md`

Key distinction to preserve:

- `cymbal.resolution.v1` is internal, exception-level, and resolution-only.
- The new v2 processing API is Node-facing, event-level, and owns the full canonical processed event outcome.

Avoid editing `nodejs/src/ingestion/error-tracking/` in the first implementation pass except possibly to read current assumptions.
Do not update generated MCP tools or OpenAPI types; this is not a DRF endpoint change.

## Open questions, risks, and tradeoffs

### Open questions

- What exact proto package and service name should be used: `cymbal.process.v2.CymbalProcess`, `cymbal.v2.Cymbal`, or another repo convention?
- What are the initial stable error code enum values and retry-after units?

### Resolved design decisions

- Initial drop reason enum values should include `suppressed_issue` and `suppression_rule`.
- Item processing deadlines are server-configured, not caller-provided per item.
- The gRPC API should use the same authentication model as the current HTTP Cymbal endpoint.
- Returning the whole canonical processed event is an accepted payload-size tradeoff.
- Error codes should be proto enums so typing is enforced for generated Node.js clients.
- Caller correlation IDs may be duplicated; Cymbal generates unique internal processing IDs for in-flight tracking and echoes the caller ID on outcomes.

### Risks

- A flexible error taxonomy can become vague if enum codes are not treated as stable control-flow values.
- Running HTTP and gRPC servers in one Cymbal process adds startup, shutdown, readiness, and operational complexity.
- Adapting the existing batch-oriented pipeline to independent streaming items may reveal hidden assumptions about batch ordering or shared preprocessing state.

### Tradeoffs

- Bidirectional streaming improves latency and backpressure but requires callers to handle out-of-order outcomes and choose unique caller IDs when they need unambiguous one-to-one matching.
- A small top-level outcome enum is simple for callers but pushes nuance into `error.kind`, error code enums, and drop reason enums.
- Keeping HTTP `/process` separate reduces rollout risk but may temporarily duplicate adapter logic.
- Reusing existing pipeline internals is faster and safer than a new processing core, but implementation agents should watch for places where current HTTP behavior intentionally attaches errors to events instead of returning item-level failures.
