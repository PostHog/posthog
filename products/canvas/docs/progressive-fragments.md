# Progressive canvas fragments

A freeform canvas can ship its layout first and fill in its panels one build at a time.
The layout renders placeholders; each panel is a fragment that the host swaps into the open canvas as soon as its build is ready.
The feature is gated by the `canvas-progressive-fragments` flag, evaluated per team on both the backend and the desktop host.

## Authoring model

- Layout: the normal entry (`index.html` -> `src/canvas.tsx`).
- Shared modules: every file under `src/shared/**`. The layout build owns one instance of each; fragments import them and get that instance.
- Fragments: every file `src/fragments/<name>.tsx|.jsx|.ts|.js` (nested directories allowed). Each is one independent chunk with a default-exported React component. A fragment may import bare dependencies, `../shared/*`, and private files outside `src/shared/` and `src/fragments/` (private imports are bundled into the fragment chunk). A fragment must not import another fragment (`fragment_imports_fragment` error).
- Marker: `import { CanvasFragment } from "@posthog/canvas-sdk/fragment"` and `<CanvasFragment path="fragments/revenue-chart" fallback={<Skeleton />} props={{ range }} />`. `path` is relative to `src/`, no extension. A marker with no fragment file renders `fallback` and counts as pending (`fragment_marker_without_file` warning).

The agent-facing workflow lives in `products/canvas/skills/building-canvases/SKILL.md`.

## Manifest fields

The builder adds these only when its input has `progressiveFragments: true`.
Without the flag the builder behaves as before and fragment files are ordinary files.

| Field              | Meaning                                                                                                                                           |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `fragments`        | `{ "<path>": { file, contentHash } }` for every built fragment. `file` is the hashed chunk path; `contentHash` is the sha256 of the emitted file. |
| `markers`          | Every `path` found by a static scan of `<CanvasFragment ... path="...">` across all source files, sorted and unique.                              |
| `pendingFragments` | `markers` minus the keys of `fragments`, sorted.                                                                                                  |
| `layoutHash`       | `contentHash` of the layout JS artifact. Equal hashes mean two builds share a layout.                                                             |
| `platformCss`      | Path of the platform stylesheet for this build.                                                                                                   |

`validate_builder_output` rejects malformed values: fragment keys must match `^fragments/[A-Za-z0-9_./-]+$`, every `file` must be an emitted artifact, hashes must be 64 hex characters.

## Module sharing

Fragments must not bundle React, Quill, or a shared store.
A second React copy breaks hooks and context, and a second store copy splits state between the layout and the panel.
The builder makes fragments reuse the layout's instances:

- The layout build wraps the entry in a generated module that imports every shared module and every declared dependency, then assigns `globalThis.__posthogCanvasModules = { "<key>": namespace, ... }`. Keys are bare specifiers (`react`, `react/jsx-runtime`, `@posthog/quill`, ...) limited to `project.dependencies` plus their `runtimeImports`, `@posthog/canvas-sdk`, `@posthog/canvas-sdk/fragment`, and `./src/shared/<path>` for shared files.
- The fragments build is a second esbuild call with every fragment as an entry point (`format: 'esm'`, `bundle: true`, `splitting: false`). A plugin resolves any import whose key is in the shared set to a shim module: `const m = globalThis.__posthogCanvasModules["<key>"]; export default m.default; export const { a, b } = m;`. Export names come from a metafile probe over the shared modules.
- `@posthog/canvas-sdk/fragment` is a builder-provided virtual module. `CanvasFragment` reads the fragment registry, dynamic-imports the chunk for its `path`, renders `fallback` until the import resolves, then renders the loaded component with `props`.

## Runtime messages

The artifact runtime appends a fragments IIFE to `assets/canvas-runtime.js`, emitted per build with `manifest.fragments` inlined.
It exposes `globalThis.__posthogCanvasFragments` with `base`, `fragments`, `subscribe`, `report`, and `error`.

- Host to canvas: `{ channel: "posthog-canvas", type: "set-fragments", base, fragments, platformCss }`. The runtime resolves each `file` to an absolute URL against `base`, swaps the platform stylesheet when `platformCss` changed, then notifies every subscribed marker. Markers whose entry changed re-import and remount their component, so local component state is lost.
- Canvas to host: `{ channel: "posthog-canvas", type: "fragment-rendered", path }` once a fragment's component is loaded.
- Errors use the existing `error` message with `Fragment <path>: <message>`.

## Host roll-forward rule

`FreeformCanvasView` keys the built frame on the build id and remounts on every ready build.
With the flag on and both manifests carrying `layoutHash`, the host keeps the mounted frame when the newest ready build's `layoutHash` equals the mounted build's, and posts `set-fragments` with the newer build's `fragments` and artifact base URL.
A different `layoutHash` (a layout, shared module, or dependency change) remounts as before.
`BuiltCanvas` takes an optional `fragments` prop for this and an `onFragmentRendered` callback.

## Feature flag

Key: `canvas-progressive-fragments`, evaluated per team.

- Backend: `build_service.run_canvas_build` passes `progressiveFragments: True` to the builder when the flag is on; any evaluation error counts as off.
- Desktop: the roll-forward rule and the "N of M fragments ready" build status only apply when the flag is on and `manifest.markers` exists.
- Desktop: `buildCanvasGenerationPrompt` adds `Progressive fragments: enabled.` to the generation task when the flag is on. The skill builds with fragments when the line is present and never when it is absent. The agent does not choose.

## Local testing

- Create the flag in the PostHog project the dev stack uses and roll it out to 100%.
- Start the desktop app with `POSTHOG_DESKTOP_SKILLS=local pnpm dev` (or `hogli desktop:dev`). The default `production` source serves the published skills, so an agent does not see skill changes from this checkout until the next skills release.
- The MCP server serves `services/mcp/schema/generated-tool-definitions.json`, not `tools.yaml`. After a `tools.yaml` change, regenerate the definitions or the agent reads the old tool description.

## Metrics

- `Canvas rendered` gains `fragment_count` and `pending_fragment_count`.
- `Canvas fragment rendered` fires per `fragment-rendered` message with `path` and `build_id`.
- `canvas build completed` (backend) is unchanged (`outcome`, `attempt_count`, `duration_seconds`, `error_codes`). Each fragment batch is a build, so one progressive canvas produces several events with the same `canvas_id`; count them per `source_version_id` to see how many publishes a canvas took.
