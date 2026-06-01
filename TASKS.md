---
title: Tasks
agent_instructions:
  - Each batch should be large enough for one agent session.
  - Change `- [ ]` to `- [x]` only when the whole batch is complete, tested, and committed.
  - At the end of each batch, commit the work and include a one-sentence message about what changed, anything unexpected, and any recommendations for the next agent.
  - Add short notes under a batch when useful for the next agent.
---

# Tasks

## Batch 1 — Finish server-side bidi protocol and tests

- [x] Make `cymbal-resolution` server tests pass against the new bidi `ResolveItem` / `ResolveOutcome` protocol.
  - Rewrite `rust/cymbal-resolution/tests/service_tests.rs` away from `ResolveRequest`, `Outcome`, `ItemOutcome`, `BatchSummary`, and item indexes.
  - Exercise bidi request streams with multiple items and out-of-order completion.
  - Assert overload is emitted only as `ResolveOutcome.Error { kind: ERROR_KIND_OVERLOADED }`.
  - Assert bad wire/payload/metadata format is `ERROR_KIND_INVALID_PAYLOAD`.
  - Assert unexpected resolver failures are `ERROR_KIND_UNHANDLED`.
  - Keep `LoadEvent` tests focused on subscription freshness/draining only; do not reintroduce overload or suggested batch sizing on `LoadEvent`.
  - Validate:
    - `flox activate -- bash -c "cd rust && cargo test -p cymbal-resolution"`
    - `flox activate -- bash -c "cd rust && cargo test -p cymbal-proto"`
    - `flox activate -- bash -c "cd rust && cargo fmt -p cymbal-resolution -p cymbal-proto -- --check"`
    - `git diff --check`
  - Commit when complete, tested, and green.
  - Notes: Replaced server tests with real in-process gRPC bidi client coverage for `ResolveItem` / `ResolveOutcome`, including out-of-order completion, invalid payload/metadata, unhandled resolver failures, and overload as `ErrorKind::Overloaded` only; `LoadEvent` tests now cover subscription sequence/freshness and draining only.

## Batch 2 — Implement per-endpoint bidi mux on the cymbal client

- [x] Replace the temporary one-shot streaming client path with a reusable per-endpoint bidi mux.
  - Add `rust/cymbal/src/stages/resolution/remote/mux.rs` or `stream.rs`.
  - Maintain one stream per endpoint with:
    - bounded outbound `mpsc<ResolveItem>` queue,
    - writer pump into the gRPC sink,
    - reader task demuxing `ResolveOutcome.id` to `oneshot` waiters,
    - per-stream monotonic `u64` token allocation,
    - in-flight waiter cleanup on completion, timeout, stream break, drain, and endpoint eviction.
  - On stream break, fail all in-flight items as retryable/overloaded so orchestration reroutes them.
  - Treat outbound queue full as local overload/reroute; do not block indefinitely.
  - Wire mux lifecycle into `EndpointPool` refresh/drain/evict handling.
  - Preserve existing `Subscribe` behavior for freshness/draining only.
  - Validate:
    - `flox activate -- bash -c "cd rust && cargo check -p cymbal"`
    - `flox activate -- bash -c "cd rust && cargo test -p cymbal --lib stages::resolution::remote"`
    - `flox activate -- bash -c "cd rust && cargo fmt -p cymbal -- --check"`
    - `git diff --check`
  - Commit when complete, tested, and green.
  - Notes: Added a per-endpoint `ResolveMux` with bounded admission, per-stream token demux, waiter cleanup on completion/timeout/stream break/close, and EndpointPool lifecycle wiring; current chunk retry path now submits through the mux while preserving batch-level all-or-nothing behavior for Batch 3 to split into per-exception reroutes.

## Batch 3 — Convert remote orchestration to per-exception reroute semantics

- [x] Replace batch retry summarization with per-exception submission, reroute, and reassembly.
  - Keep `partition.rs` and local resolution path unchanged unless required by types.
  - Build one logical work item per exception with a shared deadline spanning all reroutes.
  - Use the endpoint mux to submit items and await `oneshot` results.
  - Reroute `ERROR_KIND_OVERLOADED` using overload policy: exclude the endpoint for that item and apply bounded overload backoff.
  - Reroute `Retry` with generic retry policy.
  - Treat `ERROR_KIND_POISON` as terminal under current all-or-nothing policy, with a clear seam for later DLQ plumbing.
  - Treat `ERROR_KIND_INVALID_PAYLOAD` and `ERROR_KIND_UNHANDLED` as terminal batch errors.
  - Reassemble via client-side token/slot mapping; remove wire-level batch and item-index assumptions.
  - Delete or shrink `resolver/retry.rs` and `resolver/chunk.rs` logic that only exists for old streamed batch summaries.
  - Validate:
    - `flox activate -- bash -c "cd rust && cargo test -p cymbal --lib stages::resolution::remote::resolver"`
    - `flox activate -- bash -c "cd rust && cargo check -p cymbal-resolution"`
    - `flox activate -- bash -c "cd rust && cargo fmt -p cymbal -p cymbal-resolution -- --check"`
    - `git diff --check`
  - Commit when complete, tested, and green.
  - Notes: Remote resolution now flattens sampled events into one logical mux submission per exception with client-side token/slot reassembly, per-item overload/generic reroute policies under a shared deadline, terminal all-or-nothing handling for poison/invalid/unhandled outcomes, and the old batch-summary/chunk accounting removed from resolver internals. Batch 4 should update integration fixtures to assert these per-item reroutes end-to-end.

## Batch 4 — Rewrite remote integration and hardening tests

- [x] Update all cymbal remote-resolution tests to the final streaming protocol.
  - Rewrite fixtures in `rust/cymbal/tests/common/mod.rs` to implement bidi `Resolve`.
  - Update `remote_resolution.rs`, `remote_resolution_hardening.rs`, `remote_resolution_subscribe.rs`, and `remote_resolution_parity.rs`.
  - Cover:
    - happy path with multiple independent item outcomes,
    - per-item `ERROR_KIND_OVERLOADED` reroute,
    - stream break causing in-flight items to reroute,
    - endpoint drain/eviction closing muxes cleanly,
    - no load-bus overload or suggested batch-size behavior,
    - metadata JSON convention for `apple_debug_images_json`.
  - Remove assertions around `BatchSummary`, missing items in summary, item indexes, and old unary request capture.
  - Validate:
    - `flox activate -- bash -c "cd rust && cargo test -p cymbal --test remote_resolution"`
    - `flox activate -- bash -c "cd rust && cargo test -p cymbal --test remote_resolution_hardening"`
    - `flox activate -- bash -c "cd rust && cargo test -p cymbal --test remote_resolution_subscribe"`
    - `flox activate -- bash -c "cd rust && cargo test -p cymbal --test remote_resolution_parity"`
    - `git diff --check`
  - Commit when complete, tested, and green.
  - Notes: Remote integration fixtures now use the final bidi Resolve stream and record streamed `ResolveItem`s instead of old unary requests; coverage was updated for independent per-exception outcomes, per-item overload/reroute, stream-break reroute, endpoint refresh/drain mux closure, load-event freshness-only behavior, and `apple_debug_images_json` metadata. Batch 5 should focus on stale metrics/docs/terminology (the README and compatibility docs still describe old `ResolveRequest` chunking).

## Batch 5 — Cleanup metrics, docs, and final validation

- [x] Remove obsolete metric/doc surfaces and run full validation for the migration checkpoint.
  - Remove BatchSummary-derived metric labels and old request-level outcome reasons that no longer apply.
  - Add or update metrics for:
    - reroute depth,
    - `ErrorKind` counts by kind,
    - overload escalations,
    - per-endpoint admission rejections,
    - active in-flight gauges.
  - Update `rust/cymbal/README.md`, `rust/cymbal-resolution/README.md`, and `rust/cymbal/docs/compatibility.md` to match:
    - bidi Resolve,
    - `metadata` convention,
    - `ErrorKind`,
    - result-only overload backpressure,
    - `LoadEvent` as freshness/draining only.
  - Search for stale terms and remove or rewrite references to `ResolveRequest`, `ExceptionResolutionItem`, `BatchSummary`, `ItemOutcome`, `ItemReference`, `degraded`, `suggested_batch_size`, and load-bus overload.
  - Validate:
    - `flox activate -- bash -c "cd rust && cargo test -p cymbal-proto"`
    - `flox activate -- bash -c "cd rust && cargo test -p cymbal-resolution"`
    - `flox activate -- bash -c "cd rust && cargo test -p cymbal"`
    - `flox activate -- bash -c "cd rust && cargo clippy -p cymbal -p cymbal-resolution -p cymbal-proto --all-targets -- -D warnings"`
    - `flox activate -- bash -c "cd rust && cargo fmt -p cymbal -p cymbal-resolution -p cymbal-proto -- --check"`
    - `git diff --check`
  - Commit when complete, tested, and green.
  - Notes: Added final remote-resolution metrics for reroute depth, observed/emitted `ErrorKind`s, overload reroute escalation, endpoint mux admission rejection, endpoint mux in-flight, and server item in-flight; rewrote Cymbal/cymbal-resolution compatibility docs around bidi `Resolve`, JSON `metadata`, result-only overload backpressure, and freshness/draining-only `LoadEvent`; stale Cymbal protocol terminology search is clean for `rust/cymbal`, `rust/cymbal-resolution`, and `proto/cymbal/resolution/v1`.
