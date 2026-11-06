# Canvas templates

A canvas is an agent-authored browser app that runs in a sandboxed iframe and uses the injected
`ph` API to interact with PostHog.

## Creation and authoring

- Any ordinary task can create a canvas by invoking the bundled `building-canvases` skill.
- The space composer and sidebar do not have separate canvas task modes.
- The canvas index can still create an empty canvas record. Its composer starts a task with that
  canvas as the explicit target.
- Template records contain only picker metadata and starter suggestions. Canvas authoring rules
  live in the bundled canvas skills, not in template system prompts.

## Where things live

- Template metadata: `@posthog/core/canvas/canvasTemplates.ts` and `canvasTemplatesService.ts`.
- Agent task routing: `@posthog/core/canvas/generationPrompt.ts`.
- The iframe and `ph` bridge: `features/canvas/freeform/` and
  `@posthog/core/canvas/canvasDataService.ts`.
- Source, versions, drafts, and builds: `@posthog/core/canvas/dashboardsService.ts` and
  `dashboardSchemas.ts`.
