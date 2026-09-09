# Sketchpad contract

Pending edits are sent in ordered batches of at most 1000 operations. A larger
offline queue remains local while each accepted batch is removed and the next is sent.

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

The core sync client loads full history from its oldest missing sequence, even
when a recent snapshot or stream entry is already present. History formatting
lives in `sketchpadHistory.ts`; pending operation batching lives in `pendingOps.ts`.

Sketchpad streams use the shared SSE parser with a 512 KiB frame limit. The limit
counts UTF-8 bytes across chunks and resets between frames. Compilation polling
backs off from 250 ms to 5 seconds while output is unavailable.

Background Sketchpad sessions stay out of the ordinary space feed and source
menu. An explicit Sketchpad source filter can still retrieve them.

Desktop serves the frame document and its content security policy from the host
on the isolated Sketchpad session. The renderer cannot upload or replace that
document. The web fallback can use the same document builder with remote modules.
Artifact previews and Sketchpad share guest preferences, denied permissions,
network isolation, and navigation controls. Sketchpad IPC only forwards messages
from the frame's own window with the Sketchpad channel marker.

Module packaging and runtime URL handling share `moduleHosts.json`. A failed
manifest read is retried on the next request; module contents still need to match
their recorded SHA-256 digest. Failed cache writes reject all coalesced callers,
discard that queue, clean up the temporary file, and allow a fresh write to retry.

HTTP status mapping applies only to Sketchpad host procedures. Other host
procedures retain their existing error behavior.

The vendored-module lock also records exact download URLs for version-range
imports. Restoring the lock fetches those pinned versions and verifies the
existing hashes. Updating the lock resolves range imports once, checks that the
exact URL serves identical bytes, and records that URL for subsequent installs.

Agent tools and the sync client use the same tool names, input shapes, fragment
code rules, and ID normalization from shared `sketchpad/tools.ts`. Empty updates,
invalid geometry, and oversized shared-state values are rejected before a tool
reports success. Responses identify the normalized fragment ID and acknowledge a
queued edit; they do not claim that collaborators have received it.

The session prompt lists the imports accepted by the code guard. Tool
descriptions focus on each action. Both adapters enable Sketchpad tools only for
a nonempty Sketchpad ID. Cache expansion lives beside compaction in shared
schemas and validates each source lookup.

The host assembles its frame document from separate JavaScript and CSS sources.
The SDK and bootstrap pass through desktop linting and formatting. Source
substitution replaces each named placeholder once, leaving injected values intact.

Each mounted Sketchpad owns its request budget. Invalid edits and edits that
produce no operations do not consume write tokens. Oversized requests report a
size error separately from a full request queue. Replacing a frame resets its
readiness, state echoes, and caret digest until the replacement reports ready.

Task links persist separately from viewports. The task-link store migrates links
from the old viewport storage before viewport updates can discard them. Disabled
Sketchpad queries also hide cached results when the feature flag is turned off.

The scene measures its pane once and shares the reactive rectangle with the
stage, minimap, pointer handling, and keyboard shortcuts. Unmounted or zero-size
panes skip viewport calculations. Measurement does not pan the board.

Selection, focus, highlights, and the active panel belong to the mounted board.
Navigating to another board creates fresh transient state; persisted viewports
and task links keep their existing lifetimes. A single gesture owns pointer
capture and cleanup, including cancellation and window blur. Fragment copies use
UUIDs. The scene delegates header actions and side-panel rendering to their own
components, and its edit dialog commits synchronously.
