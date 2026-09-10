# Sketchpad contract

The shared Sketchpad schemas normalize new fragments with `z: 0`,
`codeVersion: 1`, `surface: "card"`, and `hidden: false`. Fragment patches remain
partial and do not apply those defaults.

`edit_field.initialValue` is an expected-value guard. A stale primitive value or
an ordinary object does not become a shared field locally. Field initialization
matches the server: matching primitives and arrays can initialize fields, while
ordinary objects are rejected. JSON object key order does not affect comparison.

Canvas and Sketchpad code use the shared `checkCanvasCode` guard with their
allowed import sets. It checks module imports and prohibited code-loading calls,
ignores ordinary strings and comments, and examines template expressions.
The guard gives early source feedback. It cannot prove that computed property
access is safe and is not an execution boundary. Each host must also disable
string evaluation and Node.js access, apply the restrictive frame CSP, and block
external requests.

The server retains up to 10,000 edits and returns a snapshot for the sequence
before that window. Each write carries the server sequence known when the edit
was created. A client keeps edits that get a `history_compacted` conflict so the
user can reload and reconcile them.

`SKETCHPADS_FLAG` is registered in `feature-flag-keys.json`, the desktop flag sync
source. Presence and operation schemas share the user shape; frame carets reuse
the same caret schema as presence.
