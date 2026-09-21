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

## Cold start

A module script runs before the renderer paints. The renderer entry held the
whole app, about ten megabytes, so the boot shell in `index.html` reached the
screen only when that bundle was ready. The window stayed empty until then.

`src/renderer/main.tsx` is now a boot entry of a few lines. It holds the
stylesheet import, so the shell paints styled, and imports
`src/renderer/boot.tsx` after the first frame. Rollup emits the app as its own
chunk, which drops the entry from about ten megabytes to about fifteen
kilobytes. Keep `main.tsx` this small: any import you add there paints after,
not before.

A window that is still hidden gets no animation frames, so a 500 ms timer
backs the frame up. The window itself stays hidden until `ready-to-show` in
`src/main/window.ts`, which the early paint now reaches in about 150 ms.

Keep boot work off the first screen. Syntax highlighting grammars load in
`requestIdleCallback` rather than at module scope, because a cold start does
not show a diff.

To measure a change, read `first-paint` and `first-contentful-paint` from the
renderer over CDP: `first-paint` is the boot shell, `first-contentful-paint` is
the app. `first-paint` must stay near 150 ms, whatever the app costs.
