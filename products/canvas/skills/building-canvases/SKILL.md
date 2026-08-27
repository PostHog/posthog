---
name: building-canvases
description: >
  Create or edit a PostHog freeform canvas — a sandboxed browser application (data board, document,
  form, small tool, graphics experiment) stored in PostHog and rendered by the desktop/web app. Use
  when a task asks to build, generate, update, or fix a standalone canvas app, or when a freeform
  canvas id is given as the publish target. For grid/home canvases, widget placements, or reusable
  components, use composing-grid-canvases instead. Covers resolving or creating the target canvas,
  choosing an implementation approach (React + Quill vs plain HTML/browser APIs), the read → edit →
  validate → publish → build loop, and which companion canvas skills to load for the details.
---

# Building canvases

A canvas is a client-side browser application that runs in a sandboxed iframe inside PostHog.
Its source lives in PostHog — not in a repository — and you read and write it through the
`canvas-*` tools. Never write a canvas to a local file; publishing through the tool is what
saves it.

Canvas work can start from any ordinary task. A dedicated canvas mode or pre-created canvas is
not required. When the user asks for a board, document, form, visualization, or small app that
should live in PostHog, treat that as a canvas request and follow this skill.

This skill owns `freeform` canvases (standalone apps). Two other canvas kinds exist: `grid`
canvases (widget grids, including the user's home canvas) and `component` canvases (reusable
widgets grids place). When the target is a grid or home canvas, a placement, or a reusable
widget/component, load `composing-grid-canvases` instead — it owns the store search → configure →
fork → build ladder and the layout patch loop. Authoring a component's source still uses the
implementation companions below.

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

## Load the companion skills for the implementation

This skill owns canvas selection and the authoring lifecycle. The companion skills hold the
implementation contracts. Load every companion that applies before writing source:

- **`building-react-quill-canvases`** for dashboards, data boards, forms, tools, application-like
  state, or anything that should look native to PostHog. It owns allowed imports, Quill composition,
  theming, charts, loading and error states, and the date picker.
- **`building-html-canvases`** for documents, articles, focused experiments, generative graphics,
  `<canvas>`, or WebGL work where application components add no useful structure. It owns semantic
  markup, direct browser APIs, animation cleanup, and non-Quill theming.
- **`querying-canvas-data`** whenever the canvas reads PostHog data, captures events, or navigates.
  It owns the `ph` SDK, saved-insight preference, result shapes, variables, date ranges, progressive
  per-query loading, and declared data capabilities. Load it alongside either implementation skill
  when data is involved.
- **`validating-and-publishing-canvases`** for every canvas. It owns project shape, capability
  declarations, validation diagnostics, guarded publishes, drafts, builds, and conflict recovery.

Mix implementation approaches when appropriate: React can own application chrome while browser
graphics code owns a canvas element, or a mostly static page can mount one interactive island.

This is a judgment call, not a persisted mode — ask the user only when the choice changes a
user-visible requirement you cannot infer.

## Common request patterns

Use these as routing examples, not fixed templates:

- **Product dashboard, web analytics board, or metric explorer:** React + Quill plus data querying.
- **Checklist, form, or lightweight workflow:** React + Quill, plus data querying for PostHog reads,
  event capture, or navigation. For a checklist or runbook specifically, start from the worked
  example in `building-react-quill-canvases` (`references/checklist-example.md`) — team-shared
  progress via per-step `ph.state` keys. Do not imply persistence that the available APIs do not
  provide.
- **Document or narrative report:** HTML for a mostly static reading experience; React + Quill plus
  data querying when it needs live PostHog data, filters, or application-like interactions.
- **Generative graphic or animation:** HTML and browser graphics APIs. Add React only when it
  materially simplifies application state or chrome.

When the task carries a legacy requested pattern such as `dashboard` or `web-analytics`, apply the
matching shape above. The pattern is a hint; the user's actual request remains authoritative.

## The iteration loop

1. Read the current source and version pointer with `canvas-source-retrieve`.
   Remember `current_version_id` — your publish must be guarded on it.
2. Edit the project files using the implementation companions selected above. For any PostHog data
   the canvas shows, follow `querying-canvas-data` (saved insights loaded via the `ph` SDK — never
   fetch or your own PostHog client), make every figure verifiable — an insight-backed metric
   links its saved insight in PostHog, an ad-hoc query shows the exact query that ran, per that
   skill's "Verifiability" section — and
   **declare every `ph` call in `project.capabilities`** (insight short ids in
   `capabilities.posthog.insights`, captured events in `captureEvents`, `inlineQueries: true` for
   ad-hoc queries, and `agentRequests: true` for `ph.agent.request`) — the host enforces these at
   runtime and validation rejects undeclared calls.
3. Follow `validating-and-publishing-canvases`: validate with `canvas-validate-create` as often as
   needed and fix every error-severity diagnostic.
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

## Runtime memory and actions

- **`ph.state`** — durable key-value memory: `ph.state.get(key, { scope })`,
  `ph.state.set(key, value, { scope })` (a null value deletes the key), `ph.state.list({ scope })`.
  Scope `"user"` (the default) is private to each viewer; `"shared"` is one value per canvas,
  visible to the whole team. Declare the scopes you use in `capabilities.posthog.state`.
  Values are JSON, capped at 64 KB serialized and 256 keys per scope — store big data in
  PostHog (insights, the warehouse) and reference it. Never put secrets or viewer PII in state.
- **`ph.actions.invoke(verb, payload)`** — write into PostHog as the viewer. Declare every verb
  in `capabilities.posthog.actions`; undeclared or unregistered verbs fail validation and the
  host refuses them at runtime. Wire actions to explicit user gestures (a button the viewer
  clicks), never to load or render. The registry is the source of truth: list it with the
  `canvases-actions-retrieve` tool and follow each verb's `usage` (payload/result shape,
  behavior, and the confirmation copy it warrants) before wiring it.

- **`ph.agent.request(prompt)`** — ask the canvas's authoring agent for a change, with the viewer's
  approval. Declare `agentRequests: true` in `capabilities.posthog`. Call it only from a direct
  click or form submission — the host shows the exact prompt and asks the viewer to accept before
  spending compute, and rejects calls made during render, mount, or polling. The agent stages the
  change as a draft for the canvas creator to review; a non-creator's request is filed in the
  authoring task's thread instead of starting a run.

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
