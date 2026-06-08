# Design — typed bundle authoring API (full replace of file-grain bundle writes)

**Status:** draft. **Owner:** Ben. **Tracking:** [`_TODO.md`](_TODO.md).

## 1. Problem

The bundle authoring surface today is a generic file store. The janitor accepts
arbitrary writes under arbitrary paths, and the spec carries `skills[]` and
`tools[]` arrays that the author maintains by hand alongside the files. That
loose-coupling is the root cause of an entire class of authoring failures:

| Failure mode                                                         | Why it happens                                                                                                                                                                                                                                                                |
| -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Hand-written `tools/<id>/compiled.js` ships a broken export shape    | The author can write any file at any path; the freeze-time compile produces a compiled.js but the author can also produce one, the two collide silently. Burned 122 turns / ~$2 of inference on one concierge session before we added the freeze-time guard.                  |
| Orphan files in the bundle (`orphan_skill_file`, `orphan_tool_dir`)  | The spec entry and the file are separate writes; the author can forget either half.                                                                                                                                                                                           |
| Spec drift on rename                                                 | Renaming `skills/research.md` → `skills/research-v2.md` requires both a file move AND a spec patch. Often one ships without the other; the runner silently drops the unreferenced file or 500s on the dangling reference.                                                     |
| Runtime contract is undocumented to the author                       | The runner's sandbox loader requires `{ actions: { default: fn } }`. Nothing in the authoring path enforces this — esbuild accepts a bare `export default function`; the runner rejects it at first invoke. The error (`action_not_found: default`) doesn't point at the bug. |
| Custom-tool iteration is "edit → push → freeze → run → fail → guess" | No feedback until the agent is live and the model calls the tool. Wrong shape errors don't surface until the user is mid-conversation.                                                                                                                                        |

The fix is to stop pretending the bundle is a filesystem. It isn't. It's a
collection of three typed sub-resources — the system prompt, a set of skills,
a set of custom tools — plus the native-tool / trigger / limits spec. We
should model it that way at the API and let the storage layer keep doing
whatever's convenient under the hood.

## 2. Working model — typed resources, server-derived spec

The bundle is a struct, not a file tree:

```ts
type Bundle = {
  agent_md: string // the system prompt
  skills: Skill[] // upserted by id
  tools: Tool[] // upserted by id
  spec: BundleSpec // see §6
}

type Skill = {
  id: string // url-slug shaped
  description: string // the "when to load" hint
  body: string // markdown
  files?: { path: string; content: string }[] // optional companion docs
}

type Tool = {
  id: string // url-slug shaped
  description: string // shown to the model
  args_schema: JsonSchema // the typed arg surface
  source: string // TypeScript source
  // Server-derived; never accepted from the author:
  compiled?: string // esbuild output
  shape_validated_at?: string // ISO timestamp
}
```

The spec stops carrying `skills[]` and `tools[]`. Those are server-derived from
the resources that exist. The spec the author writes shrinks to:

```ts
type BundleSpec = {
  model: string
  triggers: Trigger[]
  native_tools: string[] // e.g. "@posthog/web-fetch"
  mcps: McpRef[]
  integrations: string[] // team-wide OAuth refs
  secrets: string[] // per-app encrypted_env keys
  limits: Limits
  auth: AuthSpec
  entrypoint: string // defaults to "agent.md"
  reasoning?: 'minimal' | 'low' | 'medium' | 'high' | 'xhigh'
}
```

`skills[]` and `tools[]` in the runtime spec (what the runner reads at session
start) are reconstructed at freeze: enumerate the skill / tool resources, emit
canonical `{id, path, description}` and `{kind:'custom', id, path}` entries in
creation order. The author can't have an orphan, can't have a dangling
reference, can't ship a typo'd path. Mathematically excluded.

## 3. The HTTP surface

```text
GET    /revisions/:id/bundle              # read everything (one struct)
PUT    /revisions/:id/bundle              # full replace; missing keys delete
PUT    /revisions/:id/agent_md            # just the prompt
PUT    /revisions/:id/spec                # just the spec
PUT    /revisions/:id/skills/:skill_id    # upsert one skill
PUT    /revisions/:id/tools/:tool_id      # upsert one tool
DELETE /revisions/:id/skills/:skill_id    # remove one skill
DELETE /revisions/:id/tools/:tool_id      # remove one tool
```

That's it. No `/file?path=X`. No `/bundle` with `mode: replace | merge`. No
generic upload of arbitrary paths.

**Access patterns:**

- **Web app**: granular sub-resource PUTs / DELETEs as the user edits. Multi-
  resource flows like "save all open editors" still issue one HTTP call per
  resource — round-trip cost is fine at human-scale and the UI gets clean
  per-resource success/failure.
- **Claude Code / MCP**: `GET /bundle` → mutate in-memory → `PUT /bundle`.
  One round-trip for arbitrary multi-file changes. Matches how an LLM
  naturally edits — pull, reason about the whole picture, write the new
  state.

There is no PATCH. The PUT-full vs single-resource-PUT split covers every
realistic flow without the deletion-semantics ambiguity PATCH introduces.

## 4. What happens on `PUT /tools/:id` (the load-bearing endpoint)

This is the one with real server-side work. The naive `/file` endpoint did
nothing but write a blob; the typed endpoint runs a pipeline:

```text
1. Validate args_schema is a legal JSON Schema (zod-of-json-schema).
2. Static-AST shape check on source.ts (§5). Reject if shape is wrong.
3. esbuild transform source.ts → CJS compiled.js.
4. Re-run the shape check against the compiled output (belt-and-braces).
5. Write source.ts, compiled.js, and a derived schema.json into the bundle.
6. Stamp shape_validated_at on the revision row.
```

If any step fails, the PUT returns 422 with a precise diagnostic — line
number, expected shape, what was found. The bundle is untouched. No partial
write, no "did it land" ambiguity.

The win: shape failures surface at upload time. The author iterates on a
draft revision; freeze + promote becomes a no-op rubber stamp. Live agents
can never have a tool with the wrong runtime shape.

## 5. Sandboxing the upload-time check — AST, not Modal

The freeze-time check we ship today uses `vm.runInContext`, which Node's
docs explicitly warn is not a sandbox. The proposal moves the check
earlier (upload time) AND makes it stronger by switching to **static AST
analysis** via the TypeScript compiler API.

```text
                  parse-only static check       runtime invocation
                  (upload pipeline)              (runner at session-start)
                  ─────────────────              ──────────────────
Module loading    no code execution              vm.runInContext (today)
                                                 → Modal sandbox (prod)
Speed             ~50ms                          ~1-2s spin-up
Sandbox escape    impossible by construction     real isolation required
Catches           shape, typing of args_schema,  everything (it actually runs)
                  declarative-ness
Misses            dynamically-constructed exports  nothing
                  (we ban these on purpose)
```

The static check walks the AST:

1. Find exactly one `ExportAssignment` (`export default <expr>`).
2. Confirm `<expr>` is an `ObjectLiteralExpression`.
3. Find an `actions` property whose value is an `ObjectLiteralExpression`.
4. Find a `default` property inside `actions` whose value is a function-shaped
   node (`ArrowFunction`, `FunctionExpression`, or an object literal with a
   `run` property of the same shape).
5. Optional: cross-check the args_schema declared in the PUT body matches a
   type annotation on the default action's first parameter.

Anything dynamic — `export default makeTool()`, `actions[name] = fn`,
spread-builds — is rejected with "tool definitions must be statically
declared so the platform can analyze them ahead of run-time." This is a
deliberate restriction; the platform gains a lot of leverage from being
able to reason about the tool surface without execution.

There is **no need for Modal at upload time**. Modal stays where it matters:
the runtime sandbox the runner uses to actually invoke the tool with real
arguments and credentials. A separate, opt-in "smoke-test this tool"
endpoint (§9) is where Modal earns its keep.

## 6. Client-side validator — the fast path

We add one client tool, available to any agent whose owner is the user
editing in the console:

```jsonc
{
  "kind": "client",
  "id": "validate_custom_tool",
  "args_schema": {
    "type": "object",
    "required": ["source", "args_schema"],
    "properties": {
      "source": { "type": "string" },
      "args_schema": { "type": "object" },
    },
  },
  "description": "Validate a custom tool source.ts in the user's browser before uploading. Returns { ok, errors[], shape_summary, typecheck_diagnostics[] }. Use this iteratively while iterating on a tool — round-tripping the janitor for every typo wastes time. On non-console clients returns unhandled_client_tool; fall back to uploading and reading the 422 response.",
}
```

The web app implements it with the TypeScript web bundle (`typescript`
ships a browser build). It runs the same AST check as the server plus a
quick `tsc` typecheck against canonical `Args` / `Ctx` interfaces. Returns
identical diagnostics to the server response so the agent's reasoning
transfers between fast-loop (browser) and authoritative-loop (server).

This converts the concierge's tool-authoring loop from:

```text
draft → upload → freeze → live → invoke → fail → guess → repeat
```

to:

```text
draft → validate_locally → (fix) → validate_locally → ok → upload
```

The first loop took 122 turns on the session that motivated this work. The
second loop takes 2-4. The client tool is the single highest-leverage piece
of this design.

## 7. What this kills

Each of these is a class of bug, a class of authoring friction, or a class
of support-conversation we no longer have:

- **Orphan files** (`orphan_skill_file`, `orphan_custom_tool_dir`) — the
  warning code goes away; the failure mode it represents is impossible. We
  can delete the warning logic in `validate-spec.ts`.
- **Hand-written `compiled.js`** — there is no path to write it. The `tools`
  resource only accepts `source`. The server owns `compiled.js`.
- **Wrong-shape tools shipping live** — caught at upload. The freeze-time
  shape check becomes redundant (kept for one release as defence in depth,
  then removed).
- **Spec drift** — `spec.skills[]` and `spec.tools[]` are no longer author-
  writable. Drift requires a writer; there isn't one.
- **The `/file?path=X` endpoint** — deleted. No replacement.
- **The `mode: replace | merge` flag on `/bundle`** — deleted. PUT-full vs
  per-resource is clearer.
- **The hand-rolled "what files are allowed in a bundle" allowlist** (see
  [`bundle-manifest-schema.md`](bundle-manifest-schema.md)) — moot. The only
  files in the bundle are the ones the typed endpoints write.
- **About a third of the `authoring-new-agents` skill** — the file-shape and
  spec-shape worked examples become server-enforced and don't need to be in
  the prose.

## 8. Migration

The breakage is contained because the runner contract doesn't change. The
on-disk S3 layout is the same (`tools/<id>/{source.ts,compiled.js,schema.json}`,
`skills/<id>.md`, `agent.md`). Only the authoring API on top swaps out.

**One-shot migrator (`bin/migrate-bundles-to-typed`):**

1. For every revision (live + ready + draft), read the existing bundle file
   tree.
2. Walk `spec.skills[]`: for each entry, load the markdown body, copy
   companion files in the same dir if any. Write to the new typed `skills`
   field on the revision row (JSONB column).
3. Walk `spec.tools[]` of `kind: custom`: for each entry, load `source.ts`,
   `schema.json`. Run the new shape check; if it fails, log and skip — those
   revisions are broken and require manual fix-up.
4. Strip `skills[]` and `tools[]` from the spec JSONB.
5. Write `agent_md` from `agent.md` content.

Drafts that fail validation get flagged for the author to fix manually before
they can be edited further (since the new PUT will reject the existing bad
shape). Live agents that fail validation are left alone — the runner doesn't
care about the new authoring fields, it still reads the old S3 paths.

**Endpoints removal:**

- Delete `PUT /revisions/:id/file`, `DELETE /revisions/:id/file`,
  `GET /revisions/:id/file`.
- Delete the old `PUT /revisions/:id/bundle` mode flag; keep the URL with the
  new struct semantics.
- Keep `GET /revisions/:id/manifest` as a backwards-compat alias of
  `GET /revisions/:id/bundle` for one release, deprecated.

**Concierge skill rewrite:** the `authoring-new-agents` skill becomes the
typed-API tour. The custom-tool-source-shape table, the spec.skills /
spec.tools authoring guidance, and the "DO NOT write compiled.js" warning all
get deleted — they're now structurally impossible to get wrong. The skill
becomes ~30% shorter.

## 9. Janitor is the source of truth — Django is a proxy

This is the rule that makes everything else hold together. **The janitor's
HTTP API is the contract; Django's `/api/projects/:team_id/agent_applications/...`
endpoints are dumb pass-throughs.** Django handles auth + team scoping +
activity logging; every byte of bundle data flows through the janitor
unchanged. No request-shape translation, no Django-side schema mirror, no
"helpful" body massaging. If a field doesn't exist on the janitor endpoint,
it doesn't exist at the Django edge.

Why this matters more in the typed-API world than the file-API world:

- The typed endpoints have **real semantics** (shape checks, schema
  derivation, compile pipeline). If Django reimplements any of that to be
  "helpful," the two implementations drift and the bug class we're killing
  (silent shape mismatch) comes back through a different door.
- Web app, MCP, Claude Code, and the concierge ALL talk to the same
  janitor surface via different transports. Centralising the contract in
  one place is what lets us pin behavior with one set of tests.

### The full e2e test suite

The whole feature lives or dies on having comprehensive e2e tests against
the janitor. Lives in
[`services/agent-tests/`](../../services/agent-tests/) using the real-cluster
harness ([`buildCluster()`](../../services/agent-tests/src/harness/cluster.ts)) —
real Postgres, real S3 (SeaweedFS), real janitor HTTP server, no fakes. New
file: `services/agent-tests/src/cases/typed-bundle-authoring.test.ts`.

The cases below are the floor, not the ceiling. Each one represents a real
authoring flow or a real failure mode we've already hit. None is optional.

**Round-trip identity (the foundation):**

```text
1. GET /bundle on a fresh draft → { agent_md: "", skills: [], tools: [],
   spec: { defaults } }.
2. PUT /bundle with a fully-populated payload (agent_md + 3 skills with
   companion files + 2 tools with non-trivial source + spec).
3. GET /bundle → exact same payload back (including server-derived
   compiled.js / schema.json fields on tools).
4. Freeze → check bundle_sha256 is stable across re-freezes of the
   same content (proves the freeze is deterministic).
```

**Per-resource PUT semantics:**

```text
1. Start with a populated bundle.
2. PUT /skills/foo with a new body → GET /bundle shows updated foo, all
   other skills untouched, all tools untouched, spec untouched.
3. PUT /tools/bar with a new source → GET /bundle shows updated bar,
   compiled.js regenerated, schema.json regenerated.
4. PUT /agent_md → only agent_md changes.
5. PUT /spec → only spec changes; skills + tools preserved.
```

**DELETE semantics:**

```text
1. DELETE /skills/foo → GET /bundle no longer lists foo; foo's bundle
   files (markdown body + companions) are gone from S3.
2. DELETE /tools/bar → GET /bundle no longer lists bar; source.ts,
   compiled.js, schema.json all gone from S3.
3. DELETE a non-existent id → 404 with structured body.
4. After DELETE + freeze, the frozen spec doesn't reference the
   deleted resource (proves spec derivation runs on every freeze).
```

**Full-replace via PUT /bundle:**

```text
1. Start with { agent_md, skills: [a, b, c], tools: [x, y] }.
2. PUT /bundle with { agent_md, skills: [a, d], tools: [y, z] }.
3. GET /bundle → skills b, c are GONE; tools x is GONE. Skill d and tool
   z are present. Skill a's body matches the new payload (overwrite, not
   merge).
4. S3 has no orphan files for the deleted resources.
```

**Tool upload pipeline:**

```text
1. PUT /tools/foo with valid source → 200, source/compiled/schema all
   written, shape_validated_at stamped.
2. PUT /tools/bad with `export default async function run() {}` →
   422, body identifies the shape issue, bundle unchanged.
3. PUT /tools/bad with `export default { actions: {} }` → 422,
   "actions.default missing" message.
4. PUT /tools/bad with `export default { actions: { default: "str" } }`
   → 422, "actions.default must be callable" message.
5. PUT /tools/bad with non-deterministic source (`export default
   makeTool()`) → 422, "tool definitions must be statically declared"
   message.
6. PUT /tools/bad with a TS syntax error → 422, "source failed to
   parse: <esbuild error>" message.
7. PUT /tools/bad with args_schema that isn't a valid JSON Schema →
   422 before any compile work runs.
8. PUT /tools/foo a second time with different source → compiled.js
   regenerated, shape_validated_at advances.
```

**Spec derivation at freeze:**

```text
1. PUT /skills/a, /skills/b, /tools/x, /tools/y (no spec.skills /
   spec.tools writes — the author can't write them).
2. Freeze → fetch the frozen spec from the revision row → spec.skills
   contains a + b in creation order, spec.tools contains x + y.
3. Re-freeze a clone with same content → identical frozen spec.
4. PUT a new skill, then DELETE one of the original skills, freeze →
   frozen spec reflects the current resource set, not a stale snapshot.
```

**The validator client tool (browser parity):**

```text
1. Drive the harness with a faux model that produces a valid source.
2. Call validate_custom_tool (in-harness implementation mirrors
   browser code path).
3. Assert the validator returns identical diagnostics to the server
   PUT response — proves the fast-loop and authoritative-loop agree.
4. Repeat for every shape-failure case above.
```

**Multi-author race conditions:**

```text
1. Two clients fetch the same draft revision.
2. Client A PUTs /tools/foo.
3. Client B PUTs /skills/bar.
4. GET /bundle → both writes landed; neither stomped the other.
5. Two PUTs of /tools/foo at once → last-write-wins (we're not solving
   collaborative editing here; just confirming we don't corrupt state).
```

**Draft → ready → live lifecycle:**

```text
1. Author a draft via the typed endpoints.
2. Freeze → state=ready, bundle_sha256 stamped.
3. PUT /tools/foo against the ready revision → 422 with
   revision_not_draft (mirrors today's `requireDraft` gate).
4. Promote → state=live.
5. Start a new draft from the live revision → all typed resources
   carry forward identically.
6. PUT a change against the new draft → live revision unaffected.
```

**Migrator round-trip (one-shot, run during the rollout):**

```text
1. Seed the cluster with a pre-typed-API revision (file tree shape, spec
   carries skills[] / tools[]).
2. Run the migrator end-to-end.
3. GET /bundle on the migrated revision → returns the typed shape.
4. PUT a no-op (same payload back) → bundle_sha256 doesn't change.
5. Freeze the migrated revision → produces the same S3 layout the runner
   already reads (proves runtime contract preserved).
```

**Authentication / authorization (Django proxy regression coverage):**

```text
1. Request without team scoping → 401 from Django, never reaches
   janitor.
2. Request scoped to wrong team → 403.
3. All typed endpoints respect the same scoping rules as the legacy
   ones did (parametrised test over every endpoint).
4. Activity log entry written for every mutating call (PUT, DELETE,
   bundle PUT) — assertion via the activity-log fixture, not Django
   model snooping.
```

**What we are NOT testing here (out of scope):**

- The web app's UI behaviour — that's a frontend test.
- The runner's tool dispatch — covered by `custom-tool-sandbox.test.ts`
  already and unchanged.
- Modal sandbox safety — orthogonal, covered by sandbox-modal tests.
- Performance — separate benchmark suite; the e2e tests assert
  correctness, not latency.

### Why the e2e harness over per-service unit tests

Per-service tests miss the failure modes we care about most. Examples that
unit tests would have missed in the current codebase:

- The freeze step's bundle_sha256 stability across re-freezes (involves
  S3 + the spec derivation + esbuild's output determinism — three
  services, three different test files).
- The runner's contract that `compiled.js` is the file it loads at session
  start (involves the janitor's compile pipeline AND the runner's loader;
  any divergence between the two surfaces here, nowhere else).
- The Django proxy preserving error bodies (unit-tested Django happily
  returns `{detail: "Internal Server Error"}` while the janitor returned
  a structured 422 — proxy regression).

The harness exercises all three in one pass. Pinning the typed API
behavior in `typed-bundle-authoring.test.ts` is what lets us be aggressive
elsewhere — refactor the janitor internals, swap Django for FastAPI, move
to gRPC — without re-litigating "does the typed API still work."

## 10. Not in scope (calling out so we don't conflate)

- **`POST /tools/:id/smoke`**: opt-in "actually invoke this tool in a Modal
  sandbox with author-supplied args, return the result + logs." Separate
  feature; the upload-time AST check is sufficient on its own. This is
  where Modal actually earns its slot in the design — not at upload, but at
  optional runtime smoke test.
- **Skill schemas / typed body validation**: skills stay as plain markdown.
  A future tightening could require frontmatter shape, but that's orthogonal
  to this change.
- **Multi-revision atomic edits**: each PUT is scoped to one revision. If
  you want to edit two revisions in lockstep, that's two HTTP calls. Not
  worth solving.
- **Tarball upload for very large bundles**: bundle PUT bodies are JSON and
  capped at the existing 4MB total / 1MB per-file. Above that, presigned-S3
  upload + signed manifest is a separate plan.
- **Frontend file explorer rework**: the web app's existing file-tree UI
  needs to become a typed-resource editor. Real work, but a UI concern, not
  an API one. Tracked separately.

## 11. Open questions

1. **Skill ordering.** Without author-controlled `spec.skills[]`, the index
   the model sees is in some order. Default: creation order. Alternative:
   alphabetical by id. Either is fine; pick one and move on. _(I'd go
   creation order — it matches the author's mental model of "I added this
   later".)_
2. **Tool versioning across PUTs.** Today the bundle is content-addressed via
   sha256 at freeze. Replacing `tools/foo` on a draft is just an overwrite
   — fine. But if we add a "test history per tool version" capability later,
   we'd want per-tool monotonic versioning. Out of scope for v1; flag as
   future work.
3. **`spec` as a sub-resource vs always included in `/bundle`.** Could be
   either. I'd keep `PUT /revisions/:id/spec` as a separate endpoint AND
   accept `spec` inside the bundle PUT. The web app's spec editor is its
   own surface, so a focused endpoint is convenient.
4. **Whether skill `body` lives in the revision JSONB row or stays as a file
   in S3.** Most skills are <100KB; JSONB is comfortable. Companion `files`
   stay in S3. I'd move the body to JSONB — kills one round-trip per skill
   read and simplifies the bundle GET response.

## 12. Coupled / superseded plans

- [`bundle-manifest-schema.md`](bundle-manifest-schema.md) — **superseded.**
  The "allowed paths" allowlist is moot when the only paths are the ones
  the typed endpoints write. The plan document can be archived in the same
  PR that ships the typed API.
- [`agent-authoring-flow.md`](agent-authoring-flow.md) — needs an update
  pass: the file-grain MCP calls (`agent-applications-revisions-file-update`)
  get replaced with the typed resource calls.
- [`framework-system-prompt.md`](framework-system-prompt.md) — orthogonal
  but worth re-checking: the framework system prompt currently talks about
  bundle paths; it can be tightened to talk about typed resources instead.

## 13. Sequencing

This is a single coordinated change. There's no useful intermediate state
where half is shipped — the file API and the typed API can't coexist for
long without re-introducing the drift problems the typed API exists to kill.

Suggested PR shape:

1. **Schema + migrator** — new fields on the revision row, JSONB columns for
   `agent_md` / `skills` / `tools`, one-shot script to populate from existing
   bundles. Migrator runs in CI before the new code rolls.
2. **Janitor endpoints + e2e tests in lockstep** — new typed endpoints, old
   `/file` endpoints returning 410 Gone, `typed-bundle-authoring.test.ts`
   covering every case in §9. The tests gate the PR; if they don't pass we
   don't land the endpoints. Django proxy lands in the same PR — it's small
   enough that splitting it adds review burden without giving us anything.
3. **Web app rewrite** — file tree → typed editor. Existing skill / tool /
   agent.md panels keep their visual shape but talk to the typed endpoints.
4. **`validate_custom_tool` client tool** — TypeScript web bundle + AST check
   in the browser. High-leverage but optional.
5. **Concierge skill rewrite** — `authoring-new-agents` updated, freeze + promote
   skills updated to reflect the no-file-shape-to-mess-up world.
6. **Deletes** — old endpoints, old freeze-time shape check, `orphan_*`
   warning machinery, the `_TODO` entry for `bundle-manifest-schema.md`.

Each step is a separate PR; (1) and (2) MUST land in the same release; (3)
and (4) can follow.
