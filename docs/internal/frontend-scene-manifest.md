# Frontend scene imports

Lazy scene imports and the production chunk map come from the same manifest.
The build does not parse the generated TypeScript to recover scene IDs or import paths.

## Add or move a scene

For a product scene, edit its existing declaration in `products/<product>/manifest.tsx`.
For an app scene, edit `frontend/src/appSceneModules.mts`.
This is a plain TypeScript data object. Node 24 reads it without an added loader.
App manifest keys are runtime scene IDs, not necessarily `Scene` enum member names.
For example, `Scene.OrganizationCreateFirst` has the ID `OrganizationCreate`.
App module paths are relative to `frontend/src/`, or use an existing TypeScript path alias.

Run `pnpm build:products` from the repository root.
The commit hook also regenerates these files when a manifest or the generator changes.

The generator writes:

- `frontend/src/sceneModules.json`: the combined scene IDs and module paths.
- `frontend/src/lazySceneImports.ts`: literal `import()` calls for those modules.

Do not edit these generated files.
Each loader has one declaration, either in a product manifest or in the app manifest.
Duplicate scene IDs fail generation, even when both declarations use the same module path.
Product declarations without an `import` field supply configuration only; their loader can come from the app manifest.
An unsupported product import expression also fails generation.

`frontend/src/scenes/appScenes.ts` combines the generated lazy loaders with the existing synchronous error-page loaders.
Keep the lazy import module separate from `products.tsx` so scene changes do not become dependencies of every product metadata consumer.

## What the checks guarantee

TypeScript checks app manifest IDs against `Scene` and rejects duplicate object properties.
The generated loaders retain their exact keys and inferred module types.
A `satisfies` check requires a loader for every key in the generated manifest.
Literal imports let TypeScript and esbuild check module paths.
A module path string is not checked against the filesystem until it becomes a generated import.

The production build resolves every manifest entry through esbuild's import metadata.
A missing import or JavaScript output fails the build with the scene ID and module path.
A scene with no shared chunks has a valid empty chunk list.
Aliases can share a module and its chunk list.
The synchronous error-page loaders do not need lazy chunk entries.

These checks cover registered loaders, not every legacy value in the `Scene` enum or every route configuration.
They do not change the browser's chunk-loading behavior.

## Focused verification

Run `hogli test frontend/bin/scene-chunk-map.test.ts` for manifest generation and chunk-map coverage.
The test builds a small real esbuild graph, including a shared module and scene aliases.
Run `pnpm --filter=@posthog/frontend typescript:check` and a production frontend build before shipping generator changes.
