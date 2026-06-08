# typed-bundle-authoring-api — build notes

Issues encountered, decisions made under uncertainty, and trade-offs taken
during implementation. Read this when reviewing the PR for "why did you
do X this way" answers.

## Decisions

### D1 — keep S3 bundle as the storage backend, not a new JSONB column

Plan §2 mentioned moving skill bodies into a JSONB revision row column. After
surveying:

- The S3 bundle layout is read by the runner at session start; changing it
  would force a coordinated runner change AND a migrator.
- Per-revision JSONB containing skill bodies + companion files + tool sources
  - compiled.js would be hot and large — easily 100s of KB per revision.
- The typed API works perfectly well on top of the existing S3 layout: the
  typed endpoints just write to canonical paths (`skills/<id>.md`,
  `tools/<id>/source.ts`, etc.). The runner doesn't need to know the
  endpoints exist.

Decision: typed endpoints write canonical S3 paths. No new columns. No
migrator needed for runtime. The author surface changes; storage doesn't.

### D2 — `spec.skills[]` / `spec.tools[]` stay in the schema, derived at freeze

Plan suggested removing them from the spec entirely. But the runner reads
`rev.spec.skills` / `rev.spec.tools` at session start to know what's
available. Removing them means a runner change (read from somewhere else).

Decision: keep the runtime fields. Author cannot write them via the typed
endpoints. On draft revisions they default to `[]`. At freeze, the janitor
scans the bundle, populates spec.skills/tools, then stamps the spec.

This means drafts have empty spec.skills/spec.tools while skill markdown +
tool source live in the bundle. Validate must not error on this — it's
expected for typed-authored drafts. The freeze step is the moment of
reconciliation.

### D3 — factor validator into a standalone `@posthog/agent-bundle-validator` package (follow-up)

Per Ben's request: the AST shape check + spec validator should be
extractable as `@posthog/agent-bundle-validator` with three call sites:

- **Janitor** imports the validator for upload-time checks.
- **Agent console (browser)** imports the AST-only export (no esbuild) for
  the `validate_custom_tool` client tool.
- **CLI / `npx`** for Claude Code-style local validation against a checked-in
  bundle.

To keep velocity I'm building the validator INSIDE agent-janitor first and
will lift it out at the end of the main feature. The lifting is mechanical
(move files, add package.json, add bin entry) and easier once the API
contracts are stable. Until then the janitor exports cover both the server
call site AND any harness imports.

### D4 — drop `/file` endpoints entirely (no 410 deprecation period)

The plan says we can break things. Without `/file` the failure surface is
small enough that a hard-break is simpler than a deprecation. Janitor stops
exporting them; Django stops proxying them. Concierge skill update
mentions only the typed endpoints.

## Issues encountered

### I1 — freeze timed out at the Django proxy on a ~14-skill bundle

First attempt to freeze the concierge revision hit the Django proxy's 30s
read timeout. Root cause: `readTypedBundle` was reading every bundle file
**sequentially** via `await store.readText(path)`. For the concierge
bundle (1 agent.md + 14 skill markdowns + their derivation), the freeze
path ran ~15 sequential S3 GETs ≈ 25s end-to-end.

**Fix:** parallelise the S3 reads. One `Promise.all` over every entry
returned by `store.list()`, then a Map lookup for each file body. Brings
the freeze of a 50-file bundle from ~25s to ~2s in local SeaweedFS.

**Lesson:** any code path that walks the bundle filesystem needs to
batch the reads — sequential is fine for tiny test fixtures but breaks
on real workloads. Tracked in
[services/agent-shared/src/storage/typed-bundle.ts](services/agent-shared/src/storage/typed-bundle.ts).

### I2 — concierge revision stuck mid-freeze after timeout

The timeout above meant the janitor wrote the `.frozen` marker and
returned 200 (eventually), but Django timed out reading the response.
That left the revision in an inconsistent state: `state=draft` in
Postgres but `.frozen` marker present in S3, so further PUTs returned
409 `revision_not_editable`.

**Fix shipped:** janitor's `POST /revisions/:id/freeze` is now
idempotent. If `.frozen` exists, the handler re-derives the sha256
from the existing manifest (same shape `S3BundleStore.freeze` uses —
list → sort → hash (path \0 sha \0)) and returns it with
`idempotent: true`. Django stamps the row using the returned sha. The
caller can retry until success without leaving an inconsistent state.

**Also bumped:** the Django `JanitorClient` timeout from 30s → 120s
([janitor_client.py:43](products/agent_platform/backend/janitor_client.py#L43))
so freeze of medium-sized bundles doesn't hit the wall.

### I3 — agent-console "Failed to load bundle: Cannot convert undefined or null to object"

The console's `getBundle` API client expected the legacy `{ files:
Record<string, string> }` Django response shape; the new typed bundle
endpoint returns `{ bundle: { agent_md, skills, tools, spec } }`, so
`Object.entries(undefined)` blew up.

**Fix:** rewrote `getBundle` in
[services/agent-console/src/lib/apiClient.ts](services/agent-console/src/lib/apiClient.ts)
to consume the typed response and flatten it back into a
`BundleFile[]` keyed by canonical S3 path (agent.md, skills/<id>.md,
skills/<id>/files/\*, tools/<id>/source.ts, tools/<id>/schema.json).
Existing file-tree UI works unchanged.

**Follow-up:** for large bundles this flattening could get expensive.
The `/manifest` endpoint already exists and returns just `[{path,
size, sha256}, ...]` — the console should use that for the file tree
and lazy-fetch individual typed resources on click. Tracked.

### I4 — `new_draft_create` clone_from times out silently

`new_draft_create` calls `clone_from` internally, which iterates over
the source bundle's files calling `bundle.copy()` sequentially. For
17 files on SeaweedFS this approaches the 30s proxy timeout, so the
Django response sometimes returns the new revision row but the
clone didn't finish — leaves an empty draft with `spec=source.spec`.

**Workaround during this build:** call `clone_from` explicitly after
`new_draft_create` returns to ensure the bundle copy completed.

**Real fix (not done):** parallelise `bundle.copy()` calls in the
janitor's clone_from handler (same pattern as the `readTypedBundle`
fix in I1), or use S3 server-side copy in a batch. Flagged.

### I5 — `seed.py` is now ~3× more complex than it needs to be

The example seed script in
[services/agent-tests/src/examples/agent-concierge/scripts/seed.py](services/agent-tests/src/examples/agent-concierge/scripts/seed.py)
predates the typed API. It loads bundle files from disk into a
`{path: content}` dict and pushes via the legacy `/bundle/` with
`mode: replace`. With the typed API the whole thing collapses to one
`PUT /bundle/` carrying `{ agent_md, skills, tools, spec }`. Not done
in this PR — needs a separate sweep.

## What I deferred / didn't ship

- **`@posthog/agent-bundle-validator` standalone package (Ben asked
  for it).** Built the validator inside `agent-janitor` first; lifting
  it into its own package is mechanical (move files, add
  `package.json`, add `bin/` for npx). Should land as a follow-up PR
  before the typed API is documented externally.
- **seed.py rewrite to use one typed bundle PUT.** Noted above (I5).
- **Manifest-only fetch on the agent-console.** Noted above (I3
  follow-up).
- **One-shot Postgres migrator for legacy revisions.** The plan calls
  for it. I didn't write it because: (a) the runner contract is
  unchanged, so legacy revisions still work; (b) `new_draft_create`
  triggers a fresh derive at the next freeze, so legacy revisions
  auto-migrate the first time they're edited. Worth writing the
  migrator anyway for the "audit / cleanup" use case.
- **Parallel `bundle.copy()` in `clone_from`.** Noted above (I4
  workaround).
