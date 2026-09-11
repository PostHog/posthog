# Regex execution limits

## Legacy language URL splitter

The legacy language URL splitter accepts native JavaScript regular expressions, including lookarounds and backreferences. Matching and replacement each have a 50 ms engine execution limit for custom patterns. A limit failure raises an error through the existing transformation executor; it is not reported as a non-match and is not retried on the main execution context.

The two exact shipped default patterns retain their native fast path because they inspect only a fixed-length prefix. Editing either pattern opts that operation into the execution limit. Capture selection, replacement tokens, configuration fields and property mutation order remain unchanged. A failed replacement can therefore occur after the capture property has been assigned, as with other replacement errors.

Custom operations use fixed synchronous `node:vm` scripts. Configuration strings and event values are passed as data, never interpolated into program source. Do not add asynchronous code or callbacks to these scripts, or fall back to an unbounded native match when a deadline expires. This is an execution limit, not a memory quota or a sandbox for arbitrary JavaScript.

If a valid custom pattern reaches the limit, simplify the expression and test it against representative URLs before enabling it again. Keep the exact default patterns when their locale-prefix behavior is sufficient.

Implementation: [language URL splitter](../../nodejs/src/cdp/legacy-plugins/_transformations/language-url-splitter-app/index.ts).
Tests: [language URL splitter tests](../../nodejs/src/cdp/legacy-plugins/_transformations/language-url-splitter-app/index.test.ts).

## Browser URL previews

URL trigger and blocklist previews, including trigger-group forms, evaluate each batch in a dedicated web worker.
They preserve native JavaScript regex syntax and flags, including lookarounds and backreferences.
Each check creates a fresh expression, so global and sticky matching do not share `lastIndex` between checks.
Saved patterns and SDK matching contracts do not change.

A worker has 5000 ms to become ready, then the whole batch has a 100 ms execution budget.
Results remain pending until the batch completes.
Syntax errors appear separately from matches and non-matches.
A timeout, worker failure, or unavailable worker produces a preview error, never a non-match.
Simplify the patterns or shorten the test value if a batch times out.
Changing the test value or patterns starts a fresh request; an unchanged failed request is not retried automatically.

Every request uses a fixed source string loaded through a Blob URL.
Patterns, flags, and subjects are sent only as data through `postMessage`.
The preview does not fetch worker code from the embedding page's origin, execute supplied JavaScript, or fall back to matching on the main thread.
Browsers must support web workers and allow `blob:` worker sources in the page's Content Security Policy.
If a preview cannot start, check these browser and policy settings, then change the test value to try again.

Completion, failure, timeout, replacement, cancellation, and unmount terminate the worker and release its timers, listeners, and Blob URL.
Hiding the document also cancels an active preview; returning to the tab does not retry it.
Browser scheduling can delay delivery of the main-thread timer, so the budget is not a hard wall-clock or memory quota.
The manager also checks elapsed time when messages arrive and cancels on document hide to avoid leaving work running in a background tab.

Implementation: [worker manager](../../frontend/src/lib/regex/regexMatching.ts), [fixed worker source](../../frontend/src/lib/regex/regexWorkerSource.ts), and [preview logic](../../frontend/src/lib/regex/regexMatchingLogic.ts).

## Custom bot rule previews

The custom bot rule tester uses the same bounded worker for regex matching.
Leading `i`, `m`, and `s` flag groups are translated to native JavaScript flags, including stacked and repeated groups.
The existing bot validators still reject constructs that the backend cannot accept.
The JavaScript preview does not guarantee the same results as the backend Hyperscan engine.
Saved rules and backend validation are unchanged.

Exact, contains, and IP range conditions keep their existing matching behavior and do not need a worker.
Regex conditions in all tested rules share one worker batch and deadline.
Rule conditions still combine with the selected all/any setting.
Empty values do not match, and removing all rules that use a test field clears its preview.
The tester shows a pending state while checking rules and an error if matching cannot complete.
Simplify the regex or shorten the test value to try again.
Editing the rules or test values cancels an older request; equal inputs do not retry a failed preview.

## Toolbar event search

Plain event searches remain case-insensitive substring searches and work without web workers.
Use `/pattern/` or `/pattern/flags` for native JavaScript regex search.
The recognized flags remain `g`, `i`, `m`, `s`, `u`, and `y`.
Invalid regex syntax falls back to searching for the complete literal search string.
Each event gets a fresh expression, so global and sticky flags do not carry a match position between events.

The toolbar sends the visible event names as one batch using the worker and deadlines described above.
As events arrive, only one batch can run at a time.
A completed batch becomes visible before the toolbar checks the latest event list; incoming events do not repeatedly cancel valid work.
Completed matches remain visible while the next batch runs.
Worker failures, including browser or Content Security Policy restrictions, appear as search errors.
Simplify the pattern or use plain text to continue.
A failed pattern is not retried when events arrive, when the stream pauses or resumes, or when events are cleared.
Change the search query to try again.
Changing a query or clearing events cancels pending work, and the toolbar ignores stale results.
Category filters, pause buffering, pinned events, and exports continue to use the filtered event list.
