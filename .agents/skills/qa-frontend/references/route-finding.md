# Route Finding

Find routes by reading the code. Do not depend on a generated helper or a
hardcoded route table.

## Core App Routes

For files under `frontend/src/scenes/<scene>/...`:

1. Inspect `frontend/src/scenes/appScenes.ts` for the scene import.
2. Inspect `frontend/src/scenes/scenes.ts` for the `Scene.<Name>` route entry.
3. Prefer the concrete `urls.*` route expression or literal route string from
   `scenes.ts`.

For files under `frontend/src/lib/`, `frontend/src/queries/`, `frontend/src/types/`,
or other shared frontend areas, search for imports and choose 1-3 visible scenes
that exercise the changed surface.

## Product Routes

For files under `products/<product>/frontend/scenes/<SceneName>/...`:

1. Inspect `products/<product>/manifest.tsx`.
2. Match the changed scene directory to the manifest `scenes` import.
3. Use the manifest `routes` entry for that scene.

If the changed file is under a shared product frontend folder, search for imports
inside that product and choose the visible scene routes that use it.

## Fallbacks

Use `rg` to search for:

- The changed component, hook, or logic name.
- Nearby `urls.` references.
- Literal route strings.
- Product manifest `routes` and `treeItems` entries.

If route mapping is still unclear after a short search, add a `coverage_gap`
target. Explain which file could not be mapped and what context was checked.

Do not fabricate IDs for dynamic routes. Keep placeholders such as `:id`,
`:runId`, or `:sourceId` in the plan, then use an existing object from the UI or
create minimal safe local data only when needed.
