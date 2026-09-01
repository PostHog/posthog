---
name: validating-and-publishing-canvases
description: >
  Validate and publish a canvas source project safely: the source-project shape, declared
  capabilities, reading the current version pointer, iterating on validation diagnostics, guarded
  publishing with expected_current_version_id, staging a draft build and promoting it, waiting out
  the queued build, and recovering from a 409 version_conflict or a 429 capacity limit without
  overwriting concurrent work. Use whenever a canvas edit is ready to save, a draft build is wanted,
  a canvas publish or build returns diagnostics or a conflict, or a task needs to understand canvas
  version history.
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
- `capabilities.posthog.agentRequests: true` — when it calls `ph.agent.request`.
- `capabilities.network.origins` — each exact HTTPS origin used by `fetch`, `XMLHttpRequest`, or an
  external stylesheet, image, font, media file, or frame. Remote scripts remain blocked.
  Do not include paths, credentials, queries, fragments, or wildcards. The host must be public:
  loopback and private IPs, single-label names like `intranet`, and the `.local`, `.localhost`,
  `.internal`, and `.home.arpa` suffixes are all rejected, so a local dev host such as
  `https://localhost:8010` fails validation with an `invalid_network_origin` error. Data sent to a
  declared origin leaves PostHog and appears in the capability review before promotion.

Before validation, inventory every literal external URL in every source file. Classify navigation
links and `ph.openExternal()` URLs as navigation; they do not need a network origin. For every
request or resource URL, declare its scheme + host + optional port only. Include every origin a
request redirects to and every secondary origin a stylesheet references for fonts or images.
Never infer that one CDN hostname covers another.

Validation rejects undeclared literal calls and resource URLs (`capability_missing_*` diagnostics)
so you can fix them before publishing. Dynamic URLs and redirect destinations cannot be inferred,
so the inventory is still required even when validation is clean.

## Validate until clean

`canvas-validate-create` is side-effect free; call it as often as needed.
Diagnostics carry `severity`, a stable `code`, a `message`, and (for file-specific problems)
`path` and `line`:

- `error` diagnostics block publishing — fix all of them. Common ones: `import_not_allowed`
  (bare imports are limited to the dependencies returned in the source project),
  `forbidden_dynamic_import` / `forbidden_require` / `forbidden_inline_script`,
  `invalid_path`, `capability_missing_insight` / `capability_missing_capture_event` /
  `capability_missing_inline_queries` / `capability_missing_agent_requests` /
  `capability_missing_network_origin`,
  `dependency_not_admitted` / `dependency_version_mismatch`, and path/size violations.
- `warning` diagnostics don't block, but heed them: `network_fetch` / `network_xhr` mean the code
  reaches for the network directly. Declare the exact HTTPS origin or use the `ph` bridge.

## Publish guarded

Publishing goes live immediately, so it is for a canvas's **first version** or for a change the
user explicitly asked to make live. A canvas that already has a live version defaults to a draft
instead — see "Draft, then promote" below.

Two ways to publish, both guarded:

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

Runtime error reports (filed on the authoring task when a rendered canvas throws) name the build
they came from. A report from an **older build id** is history, not evidence about your current
code — check it against the build you just published before acting on it. In particular, a report
that a documented `ph` API is undefined (e.g. `ph.state`) means that artifact was baked by an
older host runtime: republish so a current build replaces it. Never "fix" it by removing the API
or its capability declaration.

## Draft, then promote

Publishing goes live the moment its build is ready. For a canvas that **already has a live
version**, that is not the default: stage the change as a draft and let the user promote it.
Publish directly only for a canvas's first version (nothing is live to protect) or when the user
explicitly asked to make the change live. A draft is a real, buildable version that is never the
head: the live canvas keeps rendering the current version until someone promotes the draft. This
is different from `canvas-validate-create`, which only compile-checks and produces no build or
preview.

1. **Stage** — `canvas-draft-create` with the complete `project` (same shape, capabilities, and
   validation as a publish). No `expected_current_version_id`: a draft is based on nothing and
   conflicts with nothing. The response returns the draft's `version_id`, its queued `build`, and
   `capability_widening` — the insights, capture events, inline queries, and network origins the
   draft declares beyond the live version. Surface a non-empty widening to the user before
   promoting; it is the access the change would newly grant.
2. **Wait for the build** — poll `canvas-builds-retrieve` until the draft's build is terminal, the
   same way you would after a publish. A failed draft build is fixed by staging a new draft, not by
   promoting.
3. **Preview** — read the draft's files with `canvas-source-retrieve` passing its `version_id`; once
   its build is `ready` the app renders that draft when the version is opened. The draft is **not**
   in `canvas-versions-retrieve` (that lists published history only) and cannot be reverted onto —
   list pending drafts with `canvas-drafts-retrieve`.
4. **Promote** — only when the user approved the draft or explicitly asked to go live; the
   default is to stop after staging and report the draft. `canvas-promote-create` makes the
   draft the live head. Pass
   `expected_current_version_id` (the live `current_version_id` from `canvas-source-retrieve`); it
   is guarded exactly like a publish and 409s on a moved head (recover as below). A draft whose
   build is still `ready` goes live with no rebuild; otherwise a fresh build is queued, so wait for
   it as in step 2. Promote is the only path from a draft to live.

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
