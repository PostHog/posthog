# Canvas templates

A canvas is an agent-authored single-file React app that runs in a sandboxed
iframe and talks to PostHog only through the injected `ph` shim.

## What a canvas is

- A canvas record is a `dashboard`-typed desktop-fs row whose `meta` carries the
  agent-authored React `code`, its `versions` edit history, the `currentVersionId`
  pointer, author `context`, and a `templateId`.
- **Templates** are data (`CanvasTemplate` records served by
  `CanvasTemplatesService`, listed via the `canvasTemplates` tRPC router and the
  create-picker `NewCanvasMenu`). Only **`freeform`** is offered today; more can be
  appended in `BUILT_IN_TEMPLATES` (`@posthog/core/canvas/canvasTemplates.ts`).
- A template's job is to inject the **agent system prompt**, resolved via
  `freeformSystemPromptFor`.
- Generation runs as a **dedicated agent task** (like `CONTEXT.md`) — see
  `freeformPrompt.ts` / `hooks/useGenerateFreeformCanvas.ts`.

## Where things live

- Agent prompts + templates: `@posthog/core/canvas/canvasTemplates.ts`,
  `canvasTemplatesService.ts`.
- The iframe + `ph` data shim: `features/canvas/freeform/` (`FreeformCanvas.tsx`,
  `sandboxRuntime.ts`, `freeformDataBridge.ts`) and host-side
  `@posthog/core/canvas/canvasDataService.ts`.
- Storage: `@posthog/core/canvas/dashboardsService.ts` + `dashboardSchemas.ts`.
- Deeper walkthrough of the canvas tier + the data path: the `canvas-templates`
  skill, and the forward-looking `docs/canvas-freeform-react-plan.md` (publish /
  external sharing).
