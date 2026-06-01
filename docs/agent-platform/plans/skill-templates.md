# Design — Tools & Skills registry

**Status:** active. **Owner:** ben (frontend + product), danilo (backend collaboration).
**Tracking:** TODO C5 in `services/agent-shared/TODO.md`. Supersedes the earlier
"SkillTemplate + CustomToolTemplate" draft of this doc.

## Problem

Today an agent's capabilities are scattered:

- **Native tools** (`@posthog/*`) — registered in the runner, listed at the
  janitor's `/native_tools` endpoint. Read-only, ships with the runner deploy.
- **Skills** — live as markdown in one specific agent's bundle (`skills/*.md`).
  Copying between agents means edits don't propagate; canonical PostHog-authored
  skills drift the same way.
- **Custom tools** — live as TypeScript source in one agent's bundle
  (`tools/<id>/source.ts`). Same drift problem.

The console UI mirrors this fragmentation: native tools are visible only as
opaque ids in the spec; per-bundle skills + tools have no shared home; there's
no "browse what the platform offers" surface.

We want **one registry** the human authoring console and the agent concierge
both read from:

- All native tools (read-only catalog from the runner).
- All team-scoped skill templates (markdown, optionally multi-file, versioned).
- All team-scoped custom tool templates (TS source + compiled JS + args schema,
  versioned).

Agents pin templates by `(id, version)` in `spec`. At `freeze` time the janitor
resolves each ref and **copies that version's content into the revision's
bundle** — the runner stays bundle-pure, never re-reads the registry at session
start.

## Decision summary

1. **Two new Django tables** (`agent_skill_template`, `agent_custom_tool_template`)
   plus per-template file children for multi-file skills. Native tools stay in
   the runner; they appear in the registry UI via the existing `/native_tools`
   endpoint, surfaced through the same Django facade for one fetch on the
   client.
2. **Append-only versioning** — each edit creates a new row with `version+1`
   and `is_latest=True`; the previous `is_latest` flips to `false`. Spec refs
   pin `version` numerically. Mirrors the `LLMSkill` pattern in
   `products/ai_observability` (see "Prior art" below). Reverses an earlier
   lean toward sha-based addressing — the row-per-version model makes the v1 /
   v2 / v3 version-history UI almost free.
3. **Multi-file skills from day one** — `SkillTemplateFile` child rows. Custom
   tools also support `(source.ts, compiled.js)` as the two-file convention
   inside the same versioned envelope.
4. **Structured edits API** — concierge-friendly find/replace edits applied
   sequentially with uniqueness checks. Same pattern as the existing memory
   edit tools.
5. **One frontend surface** — top-level "Registry" nav entry alongside Agents
   and Billing. Three tabs (Native tools, Skills, Custom tools). List + detail
   - version history + edit-in-place for the writable tabs.
6. **Canonical PostHog templates** seeded from in-repo markdown / source files
   via a management command. `@posthog/` is a reserved slug prefix.
7. **Referential integrity at freeze** — `spec.tools[]` / `spec.skills[]`
   JSONB stays the editable surface on drafts; freeze populates separate join
   tables (`agent_revision_skill_template`, `agent_revision_custom_tool_template`,
   `agent_revision_native_tool`) transactionally. Frozen revisions become real
   FK-checked rows; drafts stay cheap.

## Prior art

`products/ai_observability/backend/models/skills.py` ships an `LLMSkill` +
`LLMSkillFile` model with append-only versioning, structured edit endpoints,
soft delete, archive, and duplicate. The patterns are well-tested and we lift
the **shape** (versioning, files, edits, slug regex) without sharing the table
— this product solves a different runtime contract:

|                     | `LLMSkill` (ai_observability)     | This registry                                                              |
| ------------------- | --------------------------------- | -------------------------------------------------------------------------- |
| Runtime contract    | runtime fetches by name + version | janitor copies into the bundle at **freeze**; runner reads only the bundle |
| Tools?              | no                                | yes — skills and custom tools side by side                                 |
| Ref shape           | callers pass `(name, version?)`   | spec carries `{ from_template, version, alias }`                           |
| Versioning          | append-only, `is_latest` flag     | same                                                                       |
| Multi-file          | yes                               | yes                                                                        |
| Structured edits    | yes (`apply_skill_body_edits`)    | yes — same shape                                                           |
| Slug validation     | strict regex                      | same                                                                       |
| Canonical authoring | n/a                               | management command + `@posthog/` reserved prefix                           |

We **don't** reuse the `LLMSkill` table because the runtime contracts diverge
(bundle-copy vs. fetch-by-name) and we need tools, not just skills.

## Data model

Live in the **posthog DB**, same layer as `agent_application` + `agent_revision`.
All names below are slugs (lowercase a–z, 0–9, hyphen; no consecutive hyphens;
no leading or trailing hyphen — same regex as `LLMSkill`).

```sql
agent_skill_template
  id              UUID PK
  team_id         INT FK posthog_team (NULL for global / @posthog-canonical)
  name            TEXT  -- slug, `@posthog/<name>` for canonical
  description     TEXT  (≤4096)
  body            TEXT  -- the markdown that gets copied into the bundle
  version         INT   -- 1, 2, 3, …
  is_latest       BOOL  -- exactly one TRUE per (team_id, name) where deleted=false
  metadata        JSONB -- free-form, agentskills.io-compatible slot
  allowed_tools   JSONB -- list of tool ids this skill is meant to reach for
  created_by_id   INT FK posthog_user (NULL for canonical)
  created_at      TIMESTAMPTZ
  updated_at      TIMESTAMPTZ
  deleted         BOOL DEFAULT false

  UNIQUE (team_id, name, version) WHERE deleted = false
  UNIQUE (team_id, name)         WHERE deleted = false AND is_latest = true

agent_skill_template_file
  id              UUID PK
  template_id     UUID FK agent_skill_template
  path            TEXT     -- relative; no '..' segments, no leading '/'
  content         TEXT
  content_type    TEXT     -- defaults 'text/plain'
  UNIQUE (template_id, path)

agent_custom_tool_template
  id              UUID PK
  team_id         INT FK posthog_team (NULL for canonical)
  name            TEXT
  description     TEXT
  source          TEXT     -- TypeScript source
  compiled_js     TEXT     -- bundler output the runner sandboxes
  args_schema     JSONB    -- TypeBox / JSON Schema for tool args
  returns_schema  JSONB    -- optional, informational
  requires_secrets TEXT[]  -- explicit; not auto-extracted (see open question)
  version         INT
  is_latest       BOOL
  created_by_id   INT FK posthog_user (NULL for canonical)
  created_at      TIMESTAMPTZ
  updated_at      TIMESTAMPTZ
  deleted         BOOL DEFAULT false

  UNIQUE (team_id, name, version) WHERE deleted = false
  UNIQUE (team_id, name)         WHERE deleted = false AND is_latest = true
```

Notes:

- Native tools are not in the DB. They surface in the registry UI through the
  existing `/agent_native_tools/` Django proxy and are read-only.
- We store both `source` and `compiled_js` for custom tools to keep the
  freeze-time copy step deterministic — the bundler runs at edit/publish time,
  not at freeze.
- `is_latest` is a denormalised pointer for fast "give me the current version"
  reads. A trigger or a `transaction.atomic()` publish path keeps it
  consistent; the unique partial index enforces correctness.

## Referential integrity (freeze-time join tables)

`spec.tools[]` / `spec.skills[]` JSONB stays the editable surface on draft
revisions. At **freeze** we additionally write join rows so that the
authoring side can answer "which agents are stuck on v3?" with one indexed
query, and so a frozen revision can never reference a template that's been
hard-deleted.

```sql
agent_revision_skill_template
  id                  UUID PK
  revision_id         UUID FK agent_revision      ON DELETE CASCADE
  skill_template_id   UUID FK agent_skill_template
  pinned_version      INT NOT NULL
  alias               TEXT NOT NULL
  ordinal             INT NOT NULL                -- preserves spec.skills[] order
  UNIQUE (revision_id, alias)
  INDEX  (skill_template_id, pinned_version)      -- "who's on v3?" indexed lookup

agent_revision_custom_tool_template
  -- same shape, FK to agent_custom_tool_template

agent_revision_native_tool
  id                  UUID PK
  revision_id         UUID FK agent_revision      ON DELETE CASCADE
  native_tool_id      TEXT NOT NULL               -- e.g. '@posthog/query'
  ordinal             INT NOT NULL
  UNIQUE (revision_id, native_tool_id)
  INDEX  (native_tool_id)
```

Notes:

- **Drafts have no join rows.** The spec JSONB is enough — drafts can refer to
  anything (even just-deleted templates) without breaking integrity, because
  nothing pins them yet. The freeze step is the only time we look up + validate
  - insert.
- **Native tools get a separate join table.** They have no DB row to FK
  against (they live in the runner), so the table just carries the text id.
  This means "which agents use `@posthog/query`?" is also indexed, not a
  JSONB scan.
- **Hard delete becomes truly impossible** for a template that any frozen
  revision pins — the FK from `agent_revision_skill_template` blocks it. Soft
  delete (`deleted=true` + UI archive) is the only path; old frozen revisions
  keep working forever because the row still exists.
- **The "Used by" panel in the registry UI** reads only frozen revisions.
  Drafts are private WIP and would otherwise inflate counts misleadingly.

## Spec ref shape

Agents reference templates by id from their `spec`. Bundle-build at freeze
expands the ref into a real file in the revision's bundle and stamps the
resolved `version`:

```jsonc
{
  "skills": [
    {
      "from_template": "<skill_template_id>",
      "version": 3, // stamped at freeze
      "alias": "research", // becomes skills/research.md
    },
  ],
  "tools": [
    {
      "kind": "custom_template",
      "from_template": "<tool_template_id>",
      "version": 2,
      "alias": "stripe_customer_lookup",
    },
  ],
}
```

`version` is **always populated post-freeze**. Authoring drafts can omit it
(meaning "latest at freeze time") and the janitor fills it in. After freeze the
revision is wholly self-contained — the runner never re-reads the registry.

## Freeze-time semantics

When `/revisions/<id>/freeze` runs, the janitor (in a single transaction):

1. For each `spec.skills[].from_template` ref:
   - Resolve to `agent_skill_template` row at the specified version (or
     `is_latest=True` if no version pinned).
   - Copy `body` into `bundle/skills/<alias>.md`.
   - Copy each file from `agent_skill_template_file` (filtered by template_id)
     into `bundle/skills/<alias>/<path>`.
   - Stamp the resolved `version` back into the spec entry.
   - Insert an `agent_revision_skill_template` row carrying the pinned version,
     alias, and ordinal.
2. For each `spec.tools[]` with `kind: 'custom_template'`:
   - Resolve to `agent_custom_tool_template` row at the specified version.
   - Copy `source` into `bundle/tools/<alias>/source.ts`.
   - Copy `compiled_js` into `bundle/tools/<alias>/compiled.js`.
   - Stamp the resolved `version` back into the spec entry.
   - Insert an `agent_revision_custom_tool_template` row.
3. For each `spec.tools[]` with `kind: 'native'`:
   - Insert an `agent_revision_native_tool` row carrying the tool id + ordinal.
4. Compute the bundle sha as today; stamp `bundle_sha256` on the revision.

The whole thing is one `transaction.atomic()`: if any insert or copy fails the
revision stays `draft` and the bundle store is untouched. The runner never
sees the registry. The runtime contract is unchanged.

**E2E expectations** (in `services/agent-tests/`):

- Freeze of a revision whose spec references a skill template at v3 → asserts
  one row in `agent_revision_skill_template` with `pinned_version=3` and the
  alias from the spec.
- Freeze with a spec.tools[] entry where `kind: 'native'` and `id: '@posthog/query'`
  → asserts one row in `agent_revision_native_tool`.
- Hard-deleting a template that a frozen revision pins → asserts the DB
  raises `IntegrityError`; the only legal path is archive (`deleted=true`).
- Resolving "latest" at freeze time → asserts the `pinned_version` written to
  both the spec entry and the join row equals the template's `is_latest`
  version at the moment of freeze, even if a newer version lands between
  freeze and the next read.

## API surface

### REST (Django)

`SkillTemplateViewSet` and `CustomToolTemplateViewSet`, both under
`/api/projects/<team>/`:

- `GET    /agent_skill_templates/` list (latest)
- `POST   /agent_skill_templates/` create v1
- `GET    /agent_skill_templates/name/<name>/` retrieve (latest by default; `?version=N` for specific)
- `GET    /agent_skill_templates/name/<name>/versions/` version history page
- `POST   /agent_skill_templates/name/<name>/publish/` new version from edits
- `POST   /agent_skill_templates/name/<name>/archive/` soft delete
- `POST   /agent_skill_templates/name/<name>/duplicate/` clone under new name
- `POST   /agent_skill_templates/name/<name>/files/` add file
- `DELETE /agent_skill_templates/name/<name>/files/<path>/` remove file
- `POST   /agent_skill_templates/name/<name>/files-rename/` rename file
- `GET    /agent_skill_templates/name/<name>/usages/` frozen revisions pinning this template (joins on `agent_revision_skill_template`; supports `?pinned_version=N` filter)

Same shape for `agent_custom_tool_templates/` (no files endpoints — tools are
strictly `source + compiled_js`; rename via `publish`).

`AgentNativeToolsViewSet` already exists at `/agent_native_tools/`. The
registry UI reads it directly for the Native tools tab.

### MCP tools (for the concierge)

The mcp service exposes the same write surface as authoring tools:

- `agent-skill-template-list` / `-create` / `-retrieve` / `-publish` /
  `-archive` / `-duplicate` / `-rename-file` / `-create-file` / `-delete-file`
- `agent-skill-template-edit` — takes a list of structured find/replace edits,
  applies them sequentially with uniqueness checks (same as
  `apply_skill_body_edits` in `LLMSkill`).
- `agent-custom-tool-template-*` — analogous.
- `agent-native-tools-list` — already exists, no change.

The concierge uses these to write new skills / tools on the user's behalf with
the same authoring affordances a human would have.

## Structured edits (concierge-friendly)

Mirroring `LLMSkill`'s `apply_skill_body_edits`:

```jsonc
{
  "edits": [
    { "old": "## Step 1\nDo the thing", "new": "## Step 1\nDo the thing carefully" },
    { "old": "## Step 2\n", "new": "## Step 2 — gotchas\n" },
  ],
}
```

Each edit's `old` must match exactly once in the current body (else the publish
fails with the edit index + a helpful message). This is what makes diffs the
concierge produces robust against partial regenerations.

The same pattern applies to `agent_custom_tool_template` edits over `source`.

## Frontend

### Navigation

New top-level nav entry in `AppShell` sidebar, below Agents and above Billing:

- Icon: `LibraryIcon` (or `PackageIcon`)
- Route: `/registry`
- Active state matches `pathname === '/registry' || pathname.startsWith('/registry/')`

The concierge's `useSetDockConciergeAgent` declares the same `agent-concierge`
slug on `/registry/*` so the dock keeps offering the right agent.

### Routes

- `/registry` landing — three tabs (Native / Skills / Tools)
- `/registry/skills/<name>` skill detail (latest by default)
- `/registry/skills/<name>?v=N` pinned version
- `/registry/tools/<name>` custom tool detail
- `/registry/tools/<name>?v=N` pinned version
- `/registry/native/<id>` native tool detail (read-only)

### Pages

**Registry landing** (`/registry`):

- Sub-nav: `Native tools` (default) · `Skills` · `Custom tools`
- Each tab: searchable list, columns `name · description · version · updated · used by N agents`
- New-template button on the writable tabs

**Skill / custom tool detail**:

- Header: name + description + version dropdown (history)
- Body: markdown rendering for skills; source + args-schema viewer for tools
- "Files" section for skills with multi-file content
- "Usages" section: list of agent revisions that pin this version
- Edit / Publish / Archive / Duplicate actions

**Native tool detail**:

- Description, args schema (JsonView), returns schema, cost hint, requires
  (integrations + scopes)
- Linked back to the source registry in repo (read-only — no edits)
- Same dialog content that the agent Configuration tab currently opens — we
  share the component.

### Wiring into the agent Configuration tab

The existing `ConfigPanel`'s tool / skill rows currently:

- Native tool → dialog with `/agent_native_tools/` data (already done).
- Custom tool → navigates to bundle file via `onSelectBundleFile`.
- Skill → same.

After this lands, they additionally support:

- Native tool dialog grows a "Open in registry" link → `/registry/native/<id>`.
- Custom tool / skill where `kind === 'custom_template' || from_template` → link
  to `/registry/<kind>/<name>?v=<pinned>`.

The bundle file viewer stays as it is — it shows the post-freeze copy.

## Implementation steps

Roughly executable order:

1. **Backend migration + models** — five tables in one migration:
   `agent_skill_template`, `agent_skill_template_file`,
   `agent_custom_tool_template`, plus the three join tables
   (`agent_revision_skill_template`, `agent_revision_custom_tool_template`,
   `agent_revision_native_tool`). Field-level docs. Trigger or atomic publish
   helper for the `is_latest` invariant; FK + unique constraints on the joins
   per "Referential integrity" above.
2. **Serializers + viewset** — both share base behavior (list / retrieve / publish
   / archive / duplicate / version history / usages). DRF `extend_schema` on every
   action. `help_text` on every serializer field. (Per `.claude/rules/drf-endpoints.md`.)
   `usages/` reads from the join table.
3. **Structured edit service** — mirror `apply_skill_body_edits` from
   `LLMSkill`. Same error shapes so the MCP tools have parity.
4. **Janitor `freeze` integration** — extend `services/agent-janitor/src/validate-spec.ts`
   and the bundle-build pipeline to resolve `from_template` refs, copy content
   into the revision bundle, stamp `version`, and insert the corresponding
   `agent_revision_skill_template` / `agent_revision_custom_tool_template` /
   `agent_revision_native_tool` rows — all inside one `transaction.atomic()`.
5. **MCP tool surface** — add to `services/mcp/`. One pass for skill templates,
   one for custom tool templates, plus `-edit` flavored on top of the publish
   action. `agent-native-tools-list` already exists.
6. **Native tool catalog Django proxy** — already exists
   (`/agent_native_tools/`); no work, but verify the OpenAPI annotation surfaces
   the schema for client generation.
7. **Frontend `/registry` route shell** — new `app/registry/{layout,page}.tsx`.
   Tab strip. Sidebar nav entry in `AppShell`.
8. **List + detail pages** — `app/registry/skills/page.tsx`,
   `app/registry/skills/[name]/page.tsx`, same for tools and native.
   Reuse `<FileExplorer>` for multi-file skills.
9. **Editor** — markdown editor for skills (same shape as the memory editor),
   monaco-ish source viewer for tools (read-only first cut; editor in v0.1).
10. **Usages panel** — backend reads `agent_revision.spec` JSONB to count refs;
    frontend renders a small table.
11. **Canonical seed** — `seed_canonical_templates` management command,
    repo-vendored markdown + source under `products/agent_stack/backend/canonical_templates/`.
12. **Concierge integration** — ship the new MCP tools and update the concierge
    bundle's `agent.md` to describe how to use them. Verify e2e in the agent-tests
    harness.
13. **Stories + screenshots** — Storybook entries for List / Detail / Editor
    using the same fixture conventions as the rest of the agent-console.

## Open questions

- **Namespacing.** `@posthog/` reserved for canonical templates only —
  teams can't create their own `@posthog/<name>`. Already decided; documenting
  here.
- **Cross-org sharing.** Out of scope for v1. Teams own their templates.
- **Custom-tool secrets discovery.** Explicit `requires_secrets` field on the
  custom tool template, no AST extraction. Same call as in the original draft
  — extracts have been a footgun.
- **Compiled JS pipeline.** v1 keeps the existing client-side compile step; the
  editor posts both `source` and `compiled_js` together. Server-side compile is
  a follow-up.
- **Editor sophistication.** v1 ships a plain markdown editor for skills and a
  read-only source viewer for tools. Inline tool editing lands in v0.1.
- **"Recently used" / popularity sorting.** Out of scope. Plain alphabetical
  for the v1 lists.

## Out of scope (v1)

- Template approval / review workflow.
- Template usage analytics ("how often did this skill load?").
- Pre-compiling tools server-side.
- Hot-reload of a published template into an already-frozen revision. Frozen
  bundles are immutable; the authoring UI can surface "this template has a new
  version" as an opt-in rebase.
- Skill / tool **marketplaces** across orgs.

## Migration notes

- No data migration — no templates exist yet.
- Canonical seed lives at
  `products/agent_stack/backend/canonical_templates/skills/` and
  `.../custom_tools/` as plain files. The `seed_canonical_templates`
  management command reads them on deploy.

## What this unblocks

- The Slack `@agent-builder` bot (roadmap C.3) can suggest existing templates
  instead of re-deriving the same skill body from scratch each time.
- The agent concierge gets a coherent surface for "what tools/skills are
  available?" and "let me write you a new one."
- The Configuration tab in the console can deep-link to template versions, so
  reading "what does my agent actually use?" is one click away from the source.
- Future runtime MCPs that want to expose a tool catalog have a model to copy
  (write surface + version pinning + freeze-time copy).
