# Sketchpad data model

Sketchpads store a materialized board and an ordered operation log. Each board,
record, operation, and compile job belongs to a team. Use `objects.for_team(team_id)`
for access outside request scoping.

The implementation lives in `products/canvas/backend/sketchpad/`. Its presentation
package owns the API views, serializers, and actor formatting. Shared channel and
sandbox access rules come from `CanvasAccessMixin`.

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

The operation log retains history for replay and undo. Source text must remain
available while any retained operation references it, including restore snapshots.
A retention policy needs a checkpoint and an explicit response for clients whose
sequence predates that checkpoint. Removing sources by age alone breaks replay.

Sketchpad HTTP views and serializers live in `backend/presentation/sketchpad/`.
The route registry imports that presentation package. Canvas still uses its legacy
model-based presentation; the import-linter entries list the Sketchpad dependencies
explicitly until that presentation moves behind facade contracts.
