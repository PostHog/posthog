---
name: composing-grid-canvases
description: >
  Compose PostHog grid canvases — widget grids (including the user's home canvas) built from
  reusable component canvases. Use when a task asks to add, fill, move, resize, or remove a widget
  on a grid or home canvas, to compose a whole canvas of widgets from one ask, to build a reusable
  widget/component, or when a placement id or grid canvas id is the target. Covers the component
  store search → configure → fork → build ladder, the component placement contract (size,
  configSchema), the placement lifecycle (pending/generating/live/failed), the guarded layout
  patch loop, and reading the canvas's comment threads.
---

# Composing grid canvases

A grid canvas is a composition, not an app: a grid of placements, each rendering a **component
canvas** (a reusable widget with its own source, build, and placement contract). The user's home
canvas is an ordinary grid canvas in their personal channel. Layout is data — publishing or
patching one is live immediately, with no build.

Three canvas kinds share one lifecycle:

- `freeform` — a standalone app (the `building-canvases` skill owns these).
- `component` — a reusable widget. Same source/build pipeline as freeform, plus a placement
  contract. Visibility rides its channel: personal channel = private, team channel = shared.
- `grid` — a layout of placements referencing components. No file source; layout only.

## The resolution ladder: configure, fork, build

When a grid placement needs content ("a weather widget here", "a kanban of my tasks"), resolve in
this order — placing an existing component beats authoring a duplicate:

1. **Search the store**: `canvas-list` with `kind=component` and `search=<what the widget shows>`.
   A component is placeable when both `component_meta` and `published_build_id` are set. If its
   `configSchema` can express the request ("weather for Lisbon" → existing weather component with
   `config: {"location": "Lisbon"}`), place and configure it — write no code.
2. **Fork** when a component is close but its config cannot express the ask: read its source
   (`canvas-source-retrieve`), create a new component (`canvas-create` with `kind=component`),
   adapt, publish. Name the difference in the new component's description.
3. **Build new** when nothing fits — see "Building a component" below.

New components land in the channel you create them in. Create them in the same channel as the grid
they serve unless the user asks to share them more widely.

## Building a component

A component is authored exactly like a freeform canvas — load `building-react-quill-canvases` (or
`building-html-canvases`) plus `querying-canvas-data` and `validating-and-publishing-canvases` —
with three additions. A component that shows PostHog data follows the same verifiability rule as
any canvas: an insight-backed figure links its saved insight, an ad-hoc query exposes the exact
query that ran (see "Verifiability" in `querying-canvas-data`).
Start from the complete, buildable project in [references/component-example.md](references/component-example.md); its envelope, placement contract, capability declarations, and defensive `ph.state` access are the parts that break when improvised.

- **Create with `kind=component`** and a `description` written for store search: say what the
  widget shows and what its config controls. Future placements are found by this text.
- **Declare the placement contract** in the project's top-level `component` key:

  ```json
  {
    "component": {
      "size": { "defaultW": 2, "defaultH": 1, "minW": 1, "minH": 1, "maxW": 4 },
      "configSchema": {
        "type": "object",
        "properties": { "location": { "type": "string", "description": "City to show weather for" } }
      }
    }
  }
  ```

  Size is in grid units (widths 1–12, heights 1–40); `minW <= defaultW <= maxW`. The range is
  advisory: users may resize a placement to any size, so it informs defaults and warnings, never
  rejections. The config schema
  vocabulary is an allowlist — `type`, `title`, `description`, `default`, `properties`, `required`,
  `additionalProperties`, `items`, `enum`, `const`, `minimum`, `maximum`, `minLength`, `maxLength`,
  `minItems`, `maxItems`, `format`. No `$ref`, no `pattern` — validation rejects them.

- **Design responsively.** Give the component's root `h-screen` so it fills the placement iframe's
  viewport, and adapt the layout to any size the user drags: a 2×1 placement is a glanceable tile;
  a 6×4 is a full app surface. Do not use `h-full` on the root: a published component's artifact
  shell gives its `html`, `body`, and `#root` elements no explicit height, so `height: 100%`
  collapses to the content height. Render usefully at `minW`×`minH`, and treat `config` as the only
  per-placement input.

Publish and wait for the build like any canvas — a component with no ready build cannot go live on
a grid.

## Composing a whole canvas

A whole-canvas ask ("a home canvas that summarizes my work in progress") usually means several widgets, not one.
Plan the full set first — one placement per concern — then resolve each with the ladder above.
Lay them out together: no overlaps, sizes matched to what each widget shows, the grid filled deliberately rather than tiles scattered in a corner.
Batch the layout writes (one publish for an initial layout, surgical patches after) instead of one write per widget, and finish with every placement live or failed — never generating.

## Canvas comments

Users leave feedback as comment threads on the canvas, anchored to its conversation task.
List them with the task comment tools (`tasks-comments-list`, `tasks-comments-retrieve`) on your task before and after changing the canvas, and address the open ones — a comment naming a broken widget is your brief for fixing it.

## Editing a grid

The loop is read → patch, guarded exactly as `validating-and-publishing-canvases` describes for
source publishes — with `canvas-layout-get` in place of `canvas-source-retrieve`, and
`canvas-layout-patch` (surgical ops, guard required) or `canvas-layout-publish` (complete
document, for an initial layout or full restructure) as the write. On a 409, re-read the layout,
re-apply your change, and patch again.

Operations:

- `add_placement` — a new box: `{id, status, x, y, w, h, ...}`. Placements must not overlap or
  extend past `grid.columns`.
- `update_placement` — merge `changes` into the placement with `id`. Filling a drawn box is
  `{"op": "update_placement", "id": "p1", "changes": {"status": "live", "component": "<component
canvas id>", "config": {...}}}`.
- `remove_placement`, `set_grid`.

## The placement lifecycle

A placement's `status` tells the renderer what to show:

- `pending` — the user drew a box but hasn't described it (or the prompt awaits dispatch).
- `generating` — an agent task is filling it; `generationTaskId` links the task and `prompt`
  records the ask. Set this when you start working on a placement from a task.
- `live` — renders its `component` at `version` (`"latest"` by default; a pinned version id is
  allowed). Requires the component to be published and visible to the acting user.
- `failed` — generation failed; keep the `prompt` so the user can retry or re-describe.

When a task asks you to fill a placement, its prompt and the box's size are your brief: honor the
drawn `w`×`h` and keep the placement's `prompt`
intact for provenance.

## Validation you will hit

Layout publishes validate atomically; every error names its placement. The common ones:

- `component_not_found` — the id is wrong, deleted, not a component, or not visible to the acting
  user (a component in someone else's personal channel is not placeable).
- `component_not_published` — the component has never published a placement contract.
- `placement_config_invalid` — `config` does not match the component's `configSchema`.
- `placement_size_out_of_contract` — a warning, not an error: the box's `w`/`h` is outside the
  component's suggested range. The publish still succeeds; the component must render responsively.
- `placements_overlap` / `invalid_placement` — geometry; fix coordinates rather than removing the
  other widget.

End your reply by linking the grid canvas with the `url` field the canvas tools return — never
construct a canvas URL yourself.
