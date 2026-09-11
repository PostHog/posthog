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

## Session subscriptions

Command-center tiles select status fields for their own tasks through the task-to-run index.
Their view models do not keep transcript arrays alive.
PR badges and the chat footer select the output or timing fields they display.

Cloud file summaries share an incremental tool-call tracker.
Text-only appends keep the same summary identity, and tool changes produce a new snapshot without mutating a previous result.
The cache uses weak event keys so evicting a transcript can release its derived data.
Inactive review panes ignore session updates and skip tool-summary work.

Verification:

- Append text to a displayed task and another task; status-only views must not render again.
- Change permissions, completion, or run identity; the displayed status must update.
- Mount two file-summary consumers and verify that they share results, including after tool updates, history replacement, and eviction.
