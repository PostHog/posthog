---
name: building-canvases
description: >
  Create or edit a PostHog canvas — a sandboxed browser application (data board, document, form,
  small tool, graphics experiment) stored in PostHog and rendered by the desktop/web app. Use when
  a task asks to build, generate, update, or fix a canvas, or when a canvas id is given as the
  publish target. Covers resolving or creating the target canvas, choosing an implementation
  approach (React + Quill vs plain HTML/browser APIs), the read → edit → validate → publish →
  build loop, and which companion canvas skills to load for the details.
---

# Building canvases

A canvas is a client-side browser application that runs in a sandboxed iframe inside PostHog.
Its source lives in PostHog — not in a repository — and you read and write it through the
`canvas-*` tools. Never write a canvas to a local file; publishing through the tool is what
saves it.

## Resolve the target canvas

- If the task names a canvas id (canvas-initiated tasks do), that is the target. Do not create another.
- Otherwise the target channel is the one the task was created in — named in the task's context
  (the `channel_context` block or the generation instructions). List that channel's canvases with
  `canvas-list` (scope with `channel`). If one is clearly what the request refers to — an earlier
  iteration of the same board or tool — build on it instead of creating a near-duplicate, and say
  so in your reply so the user knows where the result landed.
- Only when nothing existing fits, create one with `canvas-create` in that same channel, named
  with a short descriptive title drawn from the request — never "Untitled canvas".
- Never survey channels to choose a target yourself: use `channel-list` only to resolve a channel
  the USER named to its id. Its listing puts the personal #me channel first, and #me is never a
  default — a canvas filed there is invisible to everyone else. If the task names neither a canvas
  nor a channel, ask which channel to use instead of guessing.

## Choose the least complex implementation that meets the request

- **React + Quill** — PostHog data products, dashboards, forms, application-like state, and anything
  that should look native to PostHog. Load the `building-react-quill-canvases` skill.
- **Semantic HTML, CSS, and direct browser APIs** — static documents, focused experiments, generative
  graphics, `<canvas>`/WebGL work where React adds no structure. Load the `building-html-canvases` skill.
- **Mix them** when appropriate: React can own the application chrome while Three-style code owns a
  canvas element, or a mostly static page can mount one interactive island.

This is a judgment call, not a persisted mode — ask the user only when the choice changes a
user-visible requirement you cannot infer.

## The iteration loop

1. Read the current source and version pointer with `canvas-source-retrieve`.
   Remember `current_version_id` — your publish must be guarded on it.
2. Edit the project files. For any PostHog data the canvas shows, follow the `querying-canvas-data`
   skill (saved insights loaded via the `ph` SDK — never fetch or your own PostHog client), and
   **declare every `ph` call in `project.capabilities`** (insight short ids in
   `capabilities.posthog.insights`, captured events in `captureEvents`, `inlineQueries: true` for
   ad-hoc queries) — the host enforces these at runtime and validation rejects undeclared calls.
3. Validate with `canvas-validate-create` as often as needed and fix every error-severity
   diagnostic.
4. Save the project — which tool depends on whether the canvas is already live:
   - **First version** (`current_version_id` is null): publish the complete project with
     `canvas-publish-create`, passing `expected_current_version_id: null`.
   - **Already live** (`current_version_id` is set): stage the complete project as a draft with
     `canvas-draft-create` — the user previews the draft and promotes it to live. Publish or
     promote yourself only when the user explicitly asked to make the change live.
     Follow the `validating-and-publishing-canvases` skill for diagnostics and conflict recovery.
5. **Wait for the build** — drafts and publishes alike queue one. Poll `canvas-builds-retrieve`
   (every few seconds, up to ~2 minutes) until your build is `ready` or `failed`. On `failed`,
   read the build's error diagnostics, fix the project, and save again — do not finish the
   task with a failed build.

Save once per requested change, when the canvas is ready — not after every micro-edit. When you
staged a draft, end your reply by saying a draft is ready to preview and promote; the
`validating-and-publishing-canvases` skill covers the draft → build → preview → promote flow.

End your reply by naming the channel the canvas is in and linking it with the `url` field the
canvas tools return (`canvas-create`, `canvas-list`, and the publish/source responses carry it).
That field is the only valid link to a canvas — never construct one yourself; guessed URLs
(project pages, web routes) do not resolve.

## Source-project shape

- Keep `index.html` as the entry shell returned by the source tool.
- `src/canvas.tsx` remains the conventional React entry component, but it may import additional
  relative TypeScript, TSX, JavaScript, JSON, SVG, CSS, and admitted asset files from the project.
- Self-contained module workers may be imported with `./worker.ts?worker`. A worker must not import
  another local module.
- Binary assets belong in the project's `assets` map as base64 content with an admitted content type.
  PNG, JPEG, GIF, WebP, AVIF, WOFF/WOFF2, WebAssembly, and generic octet-stream assets are supported.
- Keep the platform dependency map exactly as returned. Do not add npm packages; local relative
  imports are project files, while bare imports remain limited to the platform-pinned set.
