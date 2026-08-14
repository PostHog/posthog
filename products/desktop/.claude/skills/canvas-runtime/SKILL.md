---
name: canvas-runtime
description: How PostHog Desktop canvases run end-to-end — the built-artifact and srcDoc render paths, the `ph.*` data bridge from the sandboxed iframe to the PostHog API, capability gating, and the source/version/draft/build pipeline. Use when changing the canvas sandbox, the `ph.*` bridge, canvas data fetching, the build/draft/publish plumbing, canvas templates, or the canvas generation prompt.
---

# Canvas runtime & data

A canvas is an agent-authored browser app. Its source lives server-side, a build
service compiles it into an immutable artifact, and the app runs in a sandboxed
iframe that reaches PostHog only through the injected `ph` global. Get the render
path and the data path right and canvas work is straightforward; get them wrong and
you ship correctness bugs.

**Authoring rules are not in this package.** What the agent may import, how it
composes Quill, how it queries data, and how it publishes all live in
`products/canvas/skills/` — `building-canvases` (target resolution + the loop),
`building-react-quill-canvases`, `building-html-canvases`, `querying-canvas-data`,
`validating-and-publishing-canvases`. `generationPrompt.ts` only wraps the user's
request with the target canvas id and a pointer into `building-canvases`. Don't grow
prompt rules here; change the skill.

## The record

`DashboardRecord` (`packages/core/src/canvas/dashboardSchemas.ts`) *is* the canvas:
`channelId`, `name`, `templateId`, author-written `context`, `generationTaskId`,
`currentVersionId` (the head source version), `publishedBuildId` (the live build).
Source and history are not on the record — they come from the `source` / `versions` /
`drafts` / `builds` endpoints.

**Templates are picker metadata only.** `BUILT_IN_TEMPLATES` (`canvasTemplates.ts`)
holds one entry — `freeform` — with a name, description, and starter suggestions;
`CanvasTemplatesService.list()` serves it through `canvasTemplatesRouter.list`. There
is no per-template system prompt and no second rendering tier. Legacy records can
still carry `templateId: "web-analytics"` or `"blank"`; only `iconForTemplate` reads
those.

## Two render paths

|  | Built artifact | srcDoc sandbox |
| --- | --- | --- |
| Component | `BuiltCanvas.tsx` | `FreeformCanvas.tsx` |
| Input | signed `artifactUrl` of a finished build | one source file, transpiled in-browser |
| Transport | `MessageChannel` port into the artifact frame | `window.postMessage` on the srcDoc iframe |
| Capabilities | enforced | **not** enforced |
| Renders | the live canvas, plus pinned drafts and historical versions | a canvas with no successful build yet, and channel card previews (`FreeformPreview`) |

`FreeformCanvasView` picks in that order: a pinned artifact renders `BuiltCanvas`;
otherwise the head project's `CANVAS_COMPONENT_PATH` (`src/canvas.tsx`) renders
through the warm-frame pool; otherwise a "waiting for build" empty state.

> **⚠️ Capability gating exists only on the built path.** `assertCanvasCapability`
> (`packages/core/src/canvas/canvasCapabilities.ts`) has exactly one call site —
> `BuiltCanvas`'s `onDataRequest` wrapper — checked against the capabilities frozen
> into that build's manifest. The edit-mode bridge (`handleFreeformDataRequest`) is
> ungated, so anything you add to the bridge is reachable ungated from a
> not-yet-built canvas.

- Both iframes are `sandbox="allow-scripts"` with no `allow-same-origin`: null
  origin, no access to host storage or DOM.
- The srcDoc iframe lives in a **persistent warm pool**. `CanvasFrameHost` is mounted
  once by `WebsiteLayout` and overlays a long-lived `FreeformCanvas` onto the rect a
  `CanvasFramePlaceholder` reserves, so navigating away and back doesn't reload. The
  pool assumes **stable callbacks** — a prop whose identity changes per render (say,
  anything derived from the 2s builds poll) churns the pool and discards the warm
  frame.

## Source, versions, drafts, builds

The write format is a multi-file project (`canvasSourceProjectSchema`): `files`,
`entryHtml` (`index.html`), `dependencies`, `canvasSdkVersion`, `capabilities`.
`canvasCapabilitiesSchema` (`packages/shared/src/canvas-contracts.ts`) declares
`posthog.insights` / `posthog.inlineQueries` / `posthog.captureEvents` and
`network.origins`; a build freezes it into `canvasArtifactManifestSchema`.

**The desktop side is a relay, not the pipeline.** Validate, publish, and
draft-create are server operations the agent drives through the canvas MCP tools.
The app only reads (`source`, `versions`, `drafts`, `builds`) and mutates
`promoteDraft` / `revertToVersion` / `actOnBuild`. `DashboardsService` is the only
caller of the canvases API; `dashboards.router.ts` forwards each method one-to-one.

Version guarding is pass-through: `expectedCurrentVersionId` is required on the
promote/revert inputs and forwarded verbatim as `expected_current_version_id`. The
conflict check and its 409 are server-side — don't reimplement them here.
`canvasBuildSchemas.ts` holds the pure lifecycle helpers (`publishedCanvasBuild`,
`hasActiveCanvasBuild`, `currentHeadBuildFailure`, …).

## The data path

```
ph.query(...) / ph.loadInsight(...) / ph.capture(...)  iframe  sandboxRuntime.ts (window.ph shim)
  └─ "data-request" over postMessage / MessagePort
       └─ createCanvasHostMessageRouter                ui     canvasHostMessageRouter.ts
            └─ onDataRequest → handleFreeformDataRequest  ui  freeformDataBridge.ts
                 └─ tRPC canvasData.*                   host  canvas-data.router.ts
                      └─ CanvasDataService              core  canvasDataService.ts
                           └─ runQuery / fetchInsightByShortId   core  posthogApi.ts
                                └─ POST /api/projects/<id>/query/  (refresh: "blocking")
```

- `canvasHostMessageRouter.ts` is shared by both hosts and owns the runtime guards on
  untrusted canvas code: `MAX_CONCURRENT_DATA_REQUESTS` (8),
  `MAX_DATA_REQUEST_BYTES` (64 KB), `DATA_REQUEST_TIMEOUT_MS` (30s), and the
  `open-external` safe-URL / user-activation / one-per-second gates.
- `refresh: "blocking"` is the cached avenue insights use — serve a fresh cached
  result, else compute. Reads are additionally cached in the shared `QueryClient`
  under `CANVAS_QUERY_KEY` with a content-addressed key (`stableStringify`: sorted
  keys at every depth, `undefined` distinct from `null`), so an iframe reboot, a code
  swap, and a card preview reuse one entry. `capture` is a side effect, never cached.
- Not everything goes through `/query/`: `ph.capture` posts to `/i/v0/e/` with the
  project's *public* key, and `ph.loadInsight` reads the insights endpoint.
- `ph.openExternal` and `ph.navigate.*` never reach PostHog — the router validates and
  hands them to host callbacks. `canvasNavIntentSchema` deliberately carries no
  `channelId`, so canvas code can't navigate outside its own channel.
- `ph.run` is stubbed (`freeformDataBridge.ts` throws) — it's the published tier's
  named-insight model, where a shared canvas references allowlisted saved insights
  instead of shipping inline queries.

To add a `ph.*` capability: shim method in `sandboxRuntime.ts` → route in
`freeformDataBridge.ts` → tRPC procedure in `canvas-data.router.ts` → a
`CanvasDataService` method → a case in `assertCanvasCapability` (without one it hits
the default `throw` on the built path) → document it in `querying-canvas-data`. The
iframe never holds a token: it posts a request, the host runs the authenticated call.

> **⚠️ The result SHAPE differs by query kind — get it wrong and every value reads 0.**
> - Inline HogQL → `{ columns, results }` rows; read `results[row][col]`.
> - A typed node (`TrendsQuery`, …) → `results` is an array of **series objects**
>   (`{ data, days, count, aggregated_value, compare_label, … }`), not rows. A KPI
>   total is `results[0].count` / `.aggregated_value`; the `compareFilter` previous
>   period is a second series (match `compare_label === "previous"`, never an index).
>
> `CanvasDataService.query` row-coerces only the HogQL branch and passes typed results
> through untouched — see the `isTyped` ternary. `loadInsight` mirrors it on
> `queryKind === "HogQLQuery"`. The first build of this missed it and rendered
> all-zeros while the query ran fine.

Why the preference order (saved insight → typed node → inline HogQL) exists:
hand-rolled HogQL for standard metrics — bounce rate, sessionization, channel
attribution, unique users — subtly diverges from the product's own numbers, because
the typed nodes run the same query runners the UI does. The rule itself is
`querying-canvas-data`'s to state.

## The sandbox

`sandboxRuntime.ts` builds the entire srcDoc document: CSP, the Quill CSS links, the
import map, the Babel transform, and the `window.ph` shim.

- **CSP is per mode.** `edit` allows `'unsafe-eval'` plus esm.sh, the Tailwind CDN,
  and the PostHog hosts, because it transpiles and resolves imports in the browser.
  `view` drops the CDNs and eval entirely. `BuiltCanvas` doesn't use this document at
  all — it wraps the artifact in its own minimal host page whose CSP only permits
  framing the artifact origin.
- **Tailwind runs v4.** `TAILWIND_ENGINE = "v4"` loads `@tailwindcss/browser` and
  maps Quill's CSS variables through `@theme inline`; v4's preflight is correctly
  layered, so it needs no reset hack. The v3 Play CDN path (preflight off,
  `LEGACY_RESET`, a hand-mirrored color map) survives only as a one-constant
  fallback. Quill is authored for v4 — don't reintroduce v3 assumptions.
- **Imports are a pinned whitelist.** `FREEFORM_WHITELIST` (`freeformWhitelist.ts`)
  pins react, react-dom, `@posthog/quill`, recharts, lucide-react, and dayjs to exact
  esm.sh URLs, and `buildImportMap()` emits the import map. `FREEFORM_QUILL_CSS_URLS`
  must stay on the same `QUILL_VERSION` as the whitelist entry. `checkFreeformImports`
  exists but is **not** wired into a save path — real enforcement is server-side at
  validate/build time.
- `CANVAS_PLATFORM_MANIFEST` (`packages/shared/src/canvas-platform.ts`) vendors the
  build service's manifest (pins, allowed specifiers, CSP, size limits). It is a
  copy — change pins *with* the server, not instead of it.

## Checks after any change

```bash
pnpm --filter @posthog/core typecheck && pnpm --filter @posthog/core test
pnpm --filter @posthog/ui typecheck && pnpm --filter @posthog/ui test
npx biome lint packages/core/src/canvas packages/ui/src/features/canvas
```

Touching a skill under `products/canvas/skills/` also needs `hogli lint:skills`.

Then **verify in the running app** — the sandbox styling, the data path, the
draft/build flow, and the warm-frame pool are barely covered by unit tests. Use the
`test-electron-app` skill to drive a real canvas over CDP.
