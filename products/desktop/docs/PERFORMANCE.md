# Desktop performance

## Diff workers

Diff components own the lifetime of the syntax-highlighting worker pool.
Opening a conversation without a diff does not start workers.
Mounted diffs share one pool per renderer, capped at two workers and 200 entries in each AST cache.
The last diff unmounting releases the pool.
Languages load as files need them instead of preloading a review-wide language list.

`DiffWorkerPool` supplies the same configuration to conversation previews and code review.
Place new diff renderers inside this boundary, rather than adding a provider around a whole page.
This keeps the worker budget independent of which view opens first.

`DiffWorkerPool.test.tsx` guards the pool budget, the sharing, and the release.
To check the lifecycle in the development app, open a plain conversation, open a diff, and then leave the diff.
Inspect worker targets in Chromium DevTools: the plain conversation should have no diff workers, the diff should have two, and leaving all diffs should release them.
Check syntax highlighting and large file scrolling in both conversation previews and code review.

## Streaming transcripts

Pi text and thought chunks publish together at most once per 16 ms batch.
Tool, queue, error, and completion events flush preceding text before they apply, preserving transcript order.
Disconnect cancels pending batches, and source ID indexes reject duplicate delivery without scanning the transcript for each chunk.

Pi and ACP use the same incremental transcript builder.
Completed rows retain their identity while the active turn streams.
Pi history revisions invalidate the builder when hydration or an optimistic acknowledgement changes an earlier message.
The chat footer consumes the body's derived state instead of parsing the same transcript again.

Verification:

- Deliver a burst of chunks and check that one transcript publication contains each source ID once.
- Complete or disconnect during a pending batch and check ordering and cleanup.
- Compare incremental output with a full build at every prefix, including late events and tool updates.
- Replace an optimistic message inside a consumed prefix and check that the confirmed content appears.
