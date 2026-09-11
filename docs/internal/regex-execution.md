# Regex execution limits

## Legacy language URL splitter

The legacy language URL splitter accepts native JavaScript regular expressions, including lookarounds and backreferences. Matching and replacement each have a 50 ms engine execution limit for custom patterns. A limit failure raises an error through the existing transformation executor; it is not reported as a non-match and is not retried on the main execution context.

The two exact shipped default patterns retain their native fast path because they inspect only a fixed-length prefix. Editing either pattern opts that operation into the execution limit. Capture selection, replacement tokens, configuration fields and property mutation order remain unchanged. A failed replacement can therefore occur after the capture property has been assigned, as with other replacement errors.

Custom operations use fixed synchronous `node:vm` scripts. Configuration strings and event values are passed as data, never interpolated into program source. Do not add asynchronous code or callbacks to these scripts, or fall back to an unbounded native match when a deadline expires. This is an execution limit, not a memory quota or a sandbox for arbitrary JavaScript.

If a valid custom pattern reaches the limit, simplify the expression and test it against representative URLs before enabling it again. Keep the exact default patterns when their locale-prefix behavior is sufficient.

Implementation: [language URL splitter](../../nodejs/src/cdp/legacy-plugins/_transformations/language-url-splitter-app/index.ts).
Tests: [language URL splitter tests](../../nodejs/src/cdp/legacy-plugins/_transformations/language-url-splitter-app/index.test.ts).
