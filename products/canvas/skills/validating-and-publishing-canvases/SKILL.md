---
name: validating-and-publishing-canvases
description: >
  Validate and publish a canvas source project safely: the source-project shape, declared
  capabilities, reading the current version pointer, iterating on validation diagnostics, guarded
  publishing with expected_current_version_id, waiting out the queued build, and recovering from a
  409 version_conflict or a 429 capacity limit without overwriting concurrent work. Use whenever a
  canvas edit is ready to save, a canvas publish or build returns diagnostics or a conflict, or a
  task needs to understand canvas version history.
---

# Validating and publishing canvases

A canvas's source lives in PostHog, versioned per publish. Publishing is guarded: every edit is
based on a specific version, and the server refuses to overwrite newer work. Every publish queues
a server-side build, and the canvas renders the last successful build.

## The source project

`canvas-source-retrieve` returns:

- `project` — `schemaVersion` (1), `files` (path → content), `entryHtml` (`"index.html"`),
  `dependencies` (exact platform-pinned versions), `canvasSdkVersion`, `capabilities`.
- `current_version_id` — the version your edits are based on. Keep it; the publish needs it.
  It is `null` for a canvas that has never been published — pass that `null` on the first publish.

Keep `index.html` and `dependencies` exactly as returned. You may add relative source files and
admitted assets to the project. Use `?worker` for a self-contained module worker and represent
binary assets as base64 entries in `assets`; new npm dependencies or dependency-version drift fail
validation.

## Declare capabilities

The host enforces `project.capabilities` at runtime, so an undeclared `ph` call builds fine and
then dies in the rendered canvas. Declare:

- `capabilities.posthog.insights` — every insight short id the canvas passes to `ph.loadInsight`.
- `capabilities.posthog.captureEvents` — every event name it passes to `ph.capture`.
- `capabilities.posthog.inlineQueries: true` — when it calls `ph.query` at all.

Validation rejects undeclared literal calls (`capability_missing_*` diagnostics) so you can fix
them before publishing; dynamic ids it can only warn about, so keep the declarations complete.

## Validate until clean

`canvas-validate-create` is side-effect free; call it as often as needed.
Diagnostics carry `severity`, a stable `code`, a `message`, and (for file-specific problems)
`path` and `line`:

- `error` diagnostics block publishing — fix all of them. Common ones: `import_not_allowed`
  (bare imports are limited to react, react-dom, @posthog/quill, recharts, lucide-react, and dayjs),
  `forbidden_dynamic_import` / `forbidden_require` / `forbidden_inline_script`,
  `invalid_path`, `capability_missing_insight` / `capability_missing_capture_event` /
  `capability_missing_inline_queries`,
  `dependency_not_admitted` / `dependency_version_mismatch`, and path/size violations.
- `warning` diagnostics don't block, but heed them: `network_fetch` / `network_xhr` mean the code
  reaches for the network directly — the sandbox will block it at runtime; use the `ph` bridge.

## Publish guarded

Two ways to save, both guarded:

- **Whole project** — `canvas-publish-create` with the complete `project`.
- **Per-file edits** — `canvas-edit-create` with `operations` (each sets a
  file's complete content, or deletes it with `content: null`). Prefer this for small changes to a
  large project; the guard is mandatory here because a diff's meaning depends on its base.

For a whole-project publish with `canvas-publish-create`:

- Always pass `expected_current_version_id` — the `current_version_id` you read (or explicit
  `null` on a first publish). Unguarded publishes can silently clobber concurrent edits.
- Include a short `prompt` describing the change; it becomes the version-history entry's label.
- Pass `name` only to rename the canvas (e.g. a first build of an untitled canvas).
- Publish once per requested change. If the user asks for another edit afterwards, re-read the
  source (the head may have moved) and publish again — don't batch unrelated changes into one
  version, and don't publish work-in-progress after every micro-edit.
- A 429 means the team's build capacity is temporarily exhausted. Wait ~30 seconds and retry the
  same publish; nothing was saved.

The response returns the new `current_version_id`.

## After publishing: wait for the build

A publish queues a server-side build of the version. **The canvas does not update until the build
is ready, and nobody else is watching the result — you own it.** Poll `canvas-builds-retrieve`
every few seconds (up to ~2 minutes) until the build you queued is terminal:

- `queued`/`building` — in progress; poll again shortly.
- `ready` — the canvas's `published_build_id` advances to this build (unless a newer publish
  superseded it first). The task's canvas work is done.
- `failed` — read the build's error diagnostics, fix the project, and publish again. A failed
  build never replaces the last good one, so the canvas keeps rendering the previous version —
  finishing the task here would leave the user with a stale canvas and a silent failure.

## Recovering from 409 version_conflict

A 409 means the canvas moved past your base — a concurrent publish or a revert. The response
includes the live `current_version_id`. Never retry unguarded to force your version through:

1. Re-read the source with `canvas-source-retrieve`.
2. Re-apply your edits to the fresh source (the new head may contain someone else's changes —
   preserve them).
3. Publish again with the new `current_version_id`.

## Version history semantics

Each publish appends a full source version and moves the head pointer; users can revert to older
versions in the app (which republishes and rebuilds them). The guard matters because basing your
publish on the version you actually read is what keeps a user's revert, another agent's publish,
and your edit from silently erasing each other.
