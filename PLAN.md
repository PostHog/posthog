# Migration plan: bidi-streaming cymbal-resolution

## Goal

Replace unary-request / server-stream `Resolve` with a **bidirectional stream** of independent, id-correlated exceptions.
The server does **non-blocking per-item admission** and returns an item outcome for each accepted or rejected item.
The client **multiplexes** submissions per endpoint, **reroutes** on overload outcomes, and escalates unrecoverable overload to `UnhandledError` (DLQ).

No backward compatibility — clean rewrite at the proto level (the service is not deployed yet).

## Final protocol (`proto/cymbal/resolution/v1/resolution.proto`)

```proto
service CymbalResolution {
  rpc Resolve(stream ResolveItem) returns (stream ResolveOutcome);
  rpc Subscribe(SubscribeRequest) returns (stream LoadEvent);  // readiness/draining only
}

message ResolveItem {
  uint64 id = 1;             // per-stream correlation token
  int32  team_id = 2;
  bytes  exception_json = 3;
  bytes  metadata = 4;       // JSON metadata; convention: apple_debug_images_json key
  uint32 deadline_ms = 5;    // server self-sheds stale items
}

message ResolveOutcome {
  uint64 id = 1;
  oneof result { Done done = 2; Error error = 3; Retry retry = 4; }
}

message Error {
  ErrorKind kind = 1;
  string message = 2;
  bytes details_json = 3;
}

enum ErrorKind {
  ERROR_KIND_UNSPECIFIED = 0;
  ERROR_KIND_INVALID_PAYLOAD = 1; // bad request/wire format on our side
  ERROR_KIND_POISON = 2;          // well-formed request, bad user data; DLQ later
  ERROR_KIND_UNHANDLED = 3;       // unexpected internal failure
  ERROR_KIND_OVERLOADED = 4;      // resource exhaustion; reroute/backoff policy
}
```

`LoadEvent` keeps only subscription identity/liveness fields (`service_instance_id`, `draining`, `sequence`, `message`).
Backpressure is **not** signaled on `LoadEvent`.
Overload/backpressure happens only as a per-item `ResolveOutcome.Error { kind: OVERLOADED }`.

**Deleted:** `ResolveRequest`, `ExceptionResolutionItem`, `Outcome`, `ItemOutcome`, `BatchSummary`, `ItemReference`, all `batch_id` / `item_index` / `sequence` fields on Resolve outcomes, and the dedicated `apple_debug_images_json` protocol field.

## Error model

- Internal resolve-layer failures map to `ResolveOutcome.Error.kind`:
  - `InvalidPayload`: cymbal/cymbal-resolution protocol or payload format is wrong.
  - `Poison`: user-provided symbol/stack data is bad and should go to DLQ later.
  - `Unhandled`: unexpected service failure.
  - `Overloaded`: per-item resource exhaustion; client reroutes/backoffs using overload policy.
- `Overloaded` is never written into an event; it drives reroute + backoff within the item deadline.
  On exhaustion it escalates to `UnhandledError` (DLQ) plus a distinct metric.
- Public surface stays `resolve_batch(...) -> Result<Batch, UnhandledError>` (matches `ResolutionStage::process`), so there is **zero new pipeline-boundary surface**.
- Because every fatal path now terminates as `UnhandledError` → DLQ, the gather is plain fail-fast `try_join_all`.

## Invariants

- Resolution is idempotent (no side effects), so at-least-once reroute / double-resolution after a stream break is safe (wasted work, not incorrect).
- All-or-nothing per batch: nothing is emitted until every exception is `Done`.
- A single deadline per logical exception spans the whole reroute chain.
- Backpressure is result-only: clients do not pre-exclude pods due to load-bus overload state.

## Phases

P0–P3 land together on one branch (the proto change is a flag day that breaks both crates until client and server are updated); the tree is green again at the end of P3.

### Phase 0 — proto + codegen (flag day)

- Rewrite the `.proto` as above.
- Regenerate `cymbal-proto`.
- Rewrite `cymbal-proto/tests/contract.rs` for the new messages and `ErrorKind` enum.

### Phase 1 — server (`cymbal-resolution`)

- `service/resolve.rs`: bidi handler.
  Read inbound `ResolveItem`s; per item, **non-blocking admit** via `LoadMonitor::try_admit()`.
  Over cap ⇒ emit `Error { kind: OVERLOADED }`.
  Honor `deadline_ms` (stale/expired ⇒ `Error { kind: OVERLOADED }`).
  Spawn resolution and emit `Done` / `Error` as each finishes.
  Keep spawn + channel outbound so resolution overlaps with sends.
  Delete `BatchSummary` / missing / duplicate accounting.
- `load_monitor.rs`: keep only atomic-ish in-flight admission accounting and draining notification.
  No overload/degraded state on snapshots and no resource-exhaustion notification channel.
- Remove blocking item-admission path: drop `ItemLimiter` (the `Semaphore` wait + "limiter closed → retry").
  **Keep** `symbol_resolution_limiter` (a different concern — bounds symbol-store work).
  Update `app_context.rs`, `main.rs`, `service/mod.rs`.
- Update `service_tests.rs` for bidi streaming and `ErrorKind`.

### Phase 2 — client transport (`cymbal/src/stages/resolution/remote`)

- New `remote/mux.rs` (or `stream.rs`): per-endpoint bidi manager — outbound bounded `mpsc<ResolveItem>` (the queue), writer pump → sink, reader task demuxing `ResolveOutcome` by `id` to `oneshot` waiters; per-stream `u64` token counter; on stream break, fail all in-flight tokens as overload/retryable.
- `client.rs`: replace unary `resolve() -> Vec<Outcome>` with bidi open + half helpers (or fold into `mux.rs`).
  `RemoteCallError` classification mostly reused.
- `pool.rs`: own per-endpoint mux; tie lifecycle to `refresh` / drain / evict + reconnect.
  Reuse `select_for_key` / `select` for endpoint choice, but do **not** pre-exclude endpoints due to load pressure.
  `LoadEvent` only gates missing/stale/draining subscription state.

### Phase 3 — client orchestration (`remote/resolver`)

- `resolver.rs`: keep `partition` + local path.
  Remote path becomes per-exception: assign token, route (rendezvous), submit to endpoint mux, await `oneshot` under the shared deadline.
  - `ErrorKind::Overloaded` ⇒ reroute (exclude pod for this item + overload backoff).
  - `Retry` ⇒ generic bounded retry/reroute.
  - `ErrorKind::Poison` ⇒ DLQ path later; for now terminal batch error under all-or-nothing policy.
  - `ErrorKind::InvalidPayload` / `Unhandled` ⇒ terminal batch error.
  - deadline / all-pods-exhausted ⇒ `ResolveError::Overloaded` → escalate to `UnhandledError`.
  - gather `try_join_all`; reassemble via client-side `token → slot` map.
- Delete `chunk.rs` retry-specific batch accounting (`batch_id`, `new_batch_id`) once mux is in place.
  Keep event-atomic grouping/chunking only as a submission batching helper if still useful.
  Keep `partition.rs`.

### Phase 4 — cleanup + metrics

- Delete remaining dead code.
- Add metrics: reroute-depth histogram, `ErrorKind` count by kind, `resolution_overload_escalated_total`, per-endpoint admission rejections, in-flight gauges.
  Remove `BatchSummary`-derived metrics and any load-bus overload/suggested-batch metrics.
- Rewrite integration tests (`remote_resolution*`, the real-server subscribe / parity tests) for the streaming path.

### Phase 5 — validation

- Full `cargo build` / `clippy` / test on both crates; confirm the green checkpoint.
- Sanity-load if feasible.

## Risks / verify during build

- `LoadMonitor::try_admit` must check + increment under one lock / atomic operation (no TOCTOU between the cap check and increment).
- Stream-break + reconnect: in-flight tokens → reroute; bounded reconnect backoff (add a resolve-stream analogue of `subscribe_reconnect_backoff`).
- Deadline spans the whole reroute chain (set once); per-item timer cleanup races.
- Outbound mpsc overflow policy (define behavior when full — treat as local overload / reroute).
- gRPC bidi half-close + client-disconnect detection on the server.
- Keep overload backpressure result-only; do not reintroduce `LoadEvent` overload or suggested batch sizing.

## Deferred (not in this migration)

- Per-team fairness on a shared endpoint stream.
- Re-introducing source backpressure (vs. DLQ-on-sustained-overload) if DLQ volume proves too high.
- Final DLQ plumbing for `ErrorKind::Poison`.
