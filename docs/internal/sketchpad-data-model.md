# Sketchpad data model

Sketchpads store a materialized board and an ordered operation log. Each board,
record, operation, and compile job belongs to a team. Use `objects.for_team(team_id)`
for access outside request scoping.

The implementation lives in `products/canvas/backend/sketchpad/`. Its presentation
package owns the API views, serializers, and actor formatting. Shared channel and
sandbox access rules come from `CanvasAccessMixin`.

A snapshot holds at most 2000 fragments and 2000 state keys, the same cap as a field edit. Append requests accept at most 1000 operations. Clients split larger pending queues
into ordered batches. Sandbox attribution uses the authenticated task binding and
rejects a conflicting task ID. Desktop callers can name only tasks they can control;
the operation also records the authenticated user, independently of the claimed actor kind.

`SketchpadRecord` stores fragments, source text, compiled output, and shared state.
The record key is unique within a board and record kind. Source keys are hashes of
the source text. Record timestamps track creation and updates; operation sequence
numbers belong to `SketchpadOp`.

`SketchpadCompileJob` holds the board's compile lease, source references, compiler
version, requested sequence, expiry, and start time. The worker claims the lease
before running the compiler and checks the job identity before saving output.
Keep these checks atomic with job replacement. The compiler runs outside the
database transaction.

Serializers receive board queries annotated by `with_sketchpad_records`. They do
not fetch missing annotations. Read responses carry source references and a
source map. Replayed append responses hydrate those references into source text.

The operation log retains at most 10,000 edits for replay and undo. A checkpoint
stores the board state before the retained edits. Compaction advances it in blocks
of 1,000 edits, removes older operations, and removes source versions that no
current fragment, retained operation, or active compile job uses. A stale retry
gets a `history_compacted` conflict and remains local until the client reloads.

Sketchpad HTTP views and serializers live in `backend/presentation/sketchpad/`.
The route registry imports that presentation package. Canvas still uses its legacy
model-based presentation; the import-linter entries list the Sketchpad dependencies
explicitly until that presentation moves behind facade contracts.

## Collaboration streams

Sketchpads and notebooks use the Redis stream reader in `posthog/collab_stream.py`.
Content retains sequence IDs; ephemeral presence has separate Redis timestamp IDs
and never changes the client's `Last-Event-ID`. Presence backfill uses the Redis
clock, with the local clock as a fallback when Redis TIME fails.

Sketchpad streams check access before connecting and every 15 seconds while
reading. Removing access stops subsequent batches at the next check. Operation
frames use the same serializer as the operations API. A failed publication attempts
a reload marker at the final batch sequence with suffix `-1`, leaving the next
operation's `-0` ID available. Clients recover durable operations through the API.

SSE views can pass an async generator factory to `sse_streaming_response`; it
selects ASGI or WSGI iteration after reserving a stream slot.
