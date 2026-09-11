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

## Pi transcript residency

Pi releases transcript events and model catalogs when a view leaves an idle session.
The next visit reloads history through the session provider, as it does for an initial visit.
Session status, usage, and recovery errors remain available without retaining the transcript.

Background sessions stay subscribed while a turn, compaction, shell command, authentication restoration, queue, or permission request needs them.
A cloud run stays subscribed until its status is terminal.
Once the remaining work finishes, the controller releases the inactive transcript.
Disconnecting all sessions also releases all stored transcripts.

The controller lifecycle tests cover reopening evicted history and keeping unfinished background work alive.
For a memory check, repeatedly open and leave completed Pi tasks and collect renderer garbage after the run.
Idle transcript retention should stay flat as the number of visited tasks grows.
