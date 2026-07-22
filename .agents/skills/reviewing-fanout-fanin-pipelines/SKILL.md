---
name: reviewing-fanout-fanin-pipelines
description: >
  Review checklist for the ingestion framework's fan-out/fan-in stage
  (fanOut().via().fanIn() on chunk pipelines and the common ingestion
  skeleton). Use when writing or reviewing code that splits one pipeline
  element into per-item sub-work (per-blob uploads, per-attachment fetches),
  when deciding between fanOut, concurrently, and concurrentlyPerGroup, or
  when a sub-step returns dlq/redirect and you need the result contract.
---

# Reviewing fan-out/fan-in pipelines

How to review usage of the fan-out/fan-in stage in the Node.js ingestion pipeline framework.
The stage splits one element into N sub-elements, runs them through a regular chunk subpipeline, and folds the results back — cardinality at the parent level is preserved (N elements in, N results out).

Ground truth: `nodejs/src/ingestion/framework/fan-out-fan-in-chunk-pipeline.ts` and the living-docs chapter `nodejs/src/ingestion/framework/docs/17-fan-out-fan-in.test.ts`.
Reference adoption: the AI blob offload in `nodejs/src/ingestion/pipelines/ai/pipeline.ts`.

## When fan-out/fan-in is the right tool

| Shape of the work                                                                                                            | Use                        |
| ---------------------------------------------------------------------------------------------------------------------------- | -------------------------- |
| One element carries N independent pieces of work (blobs, attachments) that should share a concurrency cap and per-item retry | `fanOut().via().fanIn()`   |
| Each element is one piece of work; elements should process concurrently, FIFO output                                         | `concurrently`             |
| Elements must serialize within a key (e.g. per distinct_id) but keys can run concurrently                                    | `concurrentlyPerGroup`     |
| The work is per-element and cheap                                                                                            | plain `pipe` / `pipeChunk` |

Review flag: hand-rolled concurrency inside a step (`p-limit`, `Promise.all` over a worker pool) for per-item sub-work.
That fights the pipeline's `maxConcurrency` and retry machinery — it is exactly what the stage exists to replace.

## The staged API

```ts
.fanOut(extractBlobsFanOut)                    // element -> sub-elements
.via((sub) =>
    sub.concurrently((b) => b.pipe(uploadBlobStep, { retry: {...} }), {
        maxConcurrency: 8,
    })
)
.fanIn(mergeBlobPointersFanIn)                 // (original, okSubResults) -> element
```

- Available on `ChunkPipelineBuilder` and on the common ingestion skeleton (`CommonTeamStage`) — pipelines built on the skeleton do not need the `compose()` escape hatch.
- The sequence is compile-time enforced: `.fanOut()` returns an intermediate whose only method is `.via()`, which returns an intermediate whose only method is `.fanIn()`. An unclosed stage has no `build`/`handleResults`/`afterBatch`. If code stores an intermediate and passes it around, that's a smell — the chain should read in one place.
- `fanOutFn` and `fanInFn` must be **cheap, synchronous, named functions** (defined in step files, factories where they need config) — their `.name` feeds error attribution. Inline anonymous lambdas or async fan-out/fan-in functions are review flags; heavy work belongs in the subpipeline's steps.
- The `via` sub-builder is **context-agnostic** (typed over the minimal base context, not the parent's): `teamAware`, `messageAware`, `handleIngestionWarnings`, and `handleResults` are uncallable inside a sub-pipeline — sub warnings and side effects merge into the parent and are handled once by the outer pipeline. If sub-steps need team or message data, the fan-out function must put it in the sub-element value (the AI blob offload's `PendingAiBlobUpload.teamId` is the reference example).

## Result contract — what sub-steps may return

The parent **always** completes via `fanInFn(original, collected)`. Sub-results:

- **OK** — collected and handed to `fanIn`.
- **DROP** — the sanctioned way to exclude a sub-element: silent, contributes nothing; the parent fans in with the survivors (a fan-out of zero subs fans in with `[]` the same way).
- **DLQ / REDIRECT** — excluded like a drop but logs a warning at runtime. **This is a review flag**: sub-elements are not Kafka messages, so there is nothing to dead-letter or redirect. Routing decisions belong on the parent, in a step _before_ the fan-out. Fan-in functions must therefore handle receiving fewer results than were fanned out.
- Side effects and warnings from every sub-result (OK or not) merge into the parent context — nothing is double-counted, nothing is lost.
- Type consequence: sub-results cannot escape the stage, so the subpipeline's redirect names do not propagate to the stage's result type. A sub-step whose redirect output shows up in the pipeline's `handleResults` config is a sign the routing was put on the wrong side of the fan-out.
- Thrown errors are different: an exception from a sub-step (after its retries) poisons the whole stage permanently. Transient failures belong behind step retry options, and non-retriable failures that should kill only the parent belong on the parent's own steps.

## Concurrency and retry placement

- `maxConcurrency` goes on the sub `concurrently` block. One cap governs sub-elements of **all** parents in the chunk — check the value budgets for the whole chunk (e.g. the S3 socket pool), not one element.
- `retry` goes on the per-sub step (`b.pipe(step, { retry })`), so a transient failure retries only that sub-element's work, not the whole parent.
- Both knobs living anywhere else (inside the step body, on the parent step wrapping the old combined work) are review flags.

## Ordering caveat

Parents emit **unordered**, as their sub-results complete — same contract as `concurrentlyPerGroup`.
Only accept the stage where downstream sinks are order-insensitive for the affected elements; call the reordering out in review if the pipeline previously guaranteed source order.

## Related

- `ingestion-pipeline-doctor-nodejs` — general pipeline architecture, conventions, and the other doctor agents.
- `nodejs/src/ingestion/framework/docs/17-fan-out-fan-in.test.ts` — executable examples of every rule above.
