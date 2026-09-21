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

The renderer bundle is about ten megabytes. A module script in the head is
deferred, but the renderer still compiles and runs every module before it
paints, so the boot shell in `index.html` reached the screen only after the
bundle was ready. The window showed nothing for the whole of that wait.

`vite-plugin-first-paint.ts` moves the bundle out of the parsed document at
build time. An inline script loads the bundle and its module preloads after two
animation frames, so the boot shell paints first. A hidden window gets no
animation frames, so a 500 ms timer loads the bundle as well.

Keep boot work off the first screen. Syntax highlighting grammars load in
`requestIdleCallback` rather than at module scope, because a cold start does
not show a diff.

To measure a change, read `first-paint` and `first-contentful-paint` from the
renderer over CDP: `first-paint` is the boot shell, `first-contentful-paint` is
the app. `first-paint` must stay near 100 ms, whatever the bundle costs.
