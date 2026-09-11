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

## Canvas sidebar

Canvas lists above 40 entries mount the visible rows and four rows of overscan on each side.
Group headers keep their positions in the virtual list, and keyboard indexes follow the displayed group order.
The highlighted option stays mounted when scrolling so Enter can still open it.
Search and filter changes return the list to the top.

The `Canvases/CanvasList` stories provide small and 1,000-canvas fixtures.
The keyboard story checks Home, End, Enter, filtering, and clearing a search across the virtualization threshold.
Compare mounted option counts and search-clear long tasks at both narrow and wide pane widths.
