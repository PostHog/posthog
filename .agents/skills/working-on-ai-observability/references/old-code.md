# Working with older code

Older code is a fact, not a failure.
Leaving a resource in an old area is a legitimate choice.
What costs us is the mix: once old-style code sits in a layered area, nobody can tell which code to copy.

The modes, the list of old and layered areas and the definition of a bridge are in [`products/ai_observability/AGENTS.md`](../../../../products/ai_observability/AGENTS.md).
This file is for mode B, and for moving a resource.

## How to connect new code to old code

- **Build a whole slice.** A slice is one capability from view to query. All of it is in the layers.
- **Design the new side first, on its own terms.** Old request shapes, old URL parameters and old formats are adapted on the old side.
- **New code reaches old code in one of two ways.**
  - Move the piece into the layers, and import it from there in both places. Prefer this when the piece is small: a constant, a helper, a pure function.
  - When moving it is too much for this change, use it whole through one bridge module.
- **Name the bridge for what it bridges.** In the backend it is a module under `logic/<concept>/`. In the frontend it is a `*Host.tsx`.
- **New code never imports the workflow modules in `posthog/temporal/ai_observability/`.** Move the helper into product logic and import it from there in both places.
- **Old code may import new code freely.** That is the direction every dependency should end up in.
- **Switch at the outermost point.** A route, a scene or a flag picks old or new. The two never interleave inside one function or one component.
- **Read old code as a behavior spec.** List what it does (policies, limits, edge cases, telemetry), then place each behavior in its layer from scratch.
- **Delete replaced code in one cleanup.** Piece-by-piece deletion leaves orphans nobody owns.

## How not to

- A facade function that only re-exports an old-style function.
- A module under `logic/` that mixes its behavior with queries, locks and saves.
- Imports of old code scattered through new modules.
- New code that imports an old module's private helpers.
- A new module whose structure mirrors the old viewset or service it replaces.
- A wrapper named for a version.
- Half of one resource moved, so one URL's `GET` and `PATCH` live in different areas.
- A re-export shim left behind for compatibility inside the repo.

## Moving a resource into the layers

Move the whole resource, with no URL change.
Keep every `operation_id`, so generated types and MCP tools do not change.
Then make your change in mode C.
