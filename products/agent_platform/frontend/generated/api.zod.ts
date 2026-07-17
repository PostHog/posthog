/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Agent applications — the deployable unit of the platform.
 *
 * URLs:
 *     GET    /api/projects/<team>/agent_applications/             list
 *     POST   /api/projects/<team>/agent_applications/             create
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
 *     PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
 *     POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
 *     PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
 */
export const agentApplicationsCreateBodyNameMax = 255

export const agentApplicationsCreateBodySlugMax = 63

export const agentApplicationsCreateBodySlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')

export const AgentApplicationsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentApplicationsCreateBodyNameMax),
    slug: zod
        .string()
        .max(agentApplicationsCreateBodySlugMax)
        .regex(agentApplicationsCreateBodySlugRegExp)
        .optional()
        .describe(
            'Globally-unique URL identifier. Server-minted as an opaque random slug on create; only allowlisted first-party teams may set it explicitly. Slugs live in one global namespace (domain-mode ingress routing carries no team).'
        ),
    description: zod.string().optional(),
    archived: zod.boolean().optional(),
})

/**
 * Create a memory file. Fails if the path already exists — use the update endpoint to overwrite.
 */
export const agentMemoryCreateFileBodyDescriptionMax = 280

export const AgentMemoryCreateFileBody = /* @__PURE__ */ zod
    .object({
        path: zod.string().describe('Where to store the file. Lowercase a-z 0-9 _ - \/ only, must end in .md.'),
        description: zod
            .string()
            .max(agentMemoryCreateFileBodyDescriptionMax)
            .describe('One-line summary, max 280 chars. Surfaces in list\/search results.'),
        content: zod.string().describe('Full markdown body.'),
        tags: zod
            .array(zod.string())
            .optional()
            .describe('Optional flat tags for search ranking. Lowercase a-z 0-9 _ - only.'),
    })
    .describe('Body shape for AgentMemoryViewSet.write_file (create).')

/**
 * Update a memory file. Any field omitted is preserved from the existing file.
 */
export const agentMemoryUpdateFileBodyDescriptionMax = 280

export const AgentMemoryUpdateFileBody = /* @__PURE__ */ zod
    .object({
        description: zod.string().max(agentMemoryUpdateFileBodyDescriptionMax).optional(),
        content: zod.string().optional(),
        tags: zod.array(zod.string()).optional(),
    })
    .describe('Body shape for AgentMemoryViewSet.update_file. Omitted fields preserve the existing value.')

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const agentApplicationsRevisionsCreateBodyBundleUriDefault = ``

export const AgentApplicationsRevisionsCreateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod
        .string()
        .default(agentApplicationsRevisionsCreateBodyBundleUriDefault)
        .describe(
            'Storage-prefix metadata for the bundle, e.g. `fs:\/\/my-agent\/`. Optional — leave blank and the server fills `fs:\/\/<application-slug>\/`. Bundles are addressed by revision id regardless, so this is only a prefix hint.'
        ),
    spec: zod.unknown().optional(),
})

/**
 * Spec edits are only allowed while state='draft'. Once promoted to
 * ready/live the spec is frozen — change requires a new revision.
 */
export const agentApplicationsRevisionsUpdateBodyBundleUriDefault = ``

export const AgentApplicationsRevisionsUpdateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod
        .string()
        .default(agentApplicationsRevisionsUpdateBodyBundleUriDefault)
        .describe(
            'Storage-prefix metadata for the bundle, e.g. `fs:\/\/my-agent\/`. Optional — leave blank and the server fills `fs:\/\/<application-slug>\/`. Bundles are addressed by revision id regardless, so this is only a prefix hint.'
        ),
    spec: zod.unknown().optional(),
})

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const agentApplicationsRevisionsPartialUpdateBodyBundleUriDefault = ``

export const AgentApplicationsRevisionsPartialUpdateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod
        .string()
        .default(agentApplicationsRevisionsPartialUpdateBodyBundleUriDefault)
        .describe(
            'Storage-prefix metadata for the bundle, e.g. `fs:\/\/my-agent\/`. Optional — leave blank and the server fills `fs:\/\/<application-slug>\/`. Bundles are addressed by revision id regardless, so this is only a prefix hint.'
        ),
    spec: zod.unknown().optional(),
})

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const AgentApplicationsRevisionsAgentMdUpdateBody = /* @__PURE__ */ zod
    .object({
        content: zod.string(),
    })
    .describe('Body shape for PUT \/revisions\/<id>\/agent_md\/.')

/**
 * Full-replace the typed bundle. Anything not in the payload is
 * deleted. Tool sources are AST-checked + esbuild-compiled by the
 * janitor before any S3 writes.
 */
export const AgentApplicationsRevisionsBundleUpdateBody = /* @__PURE__ */ zod
    .object({
        agent_md: zod.string(),
        tools: zod
            .array(
                zod
                    .object({
                        description: zod.string(),
                        args_schema: zod.record(zod.string(), zod.unknown()),
                        source: zod.string(),
                    })
                    .describe('Body shape for PUT \/revisions\/<id>\/tools\/<tool_id>\/.')
            )
            .optional(),
        spec: zod.record(zod.string(), zod.unknown()),
    })
    .describe(
        'Body shape for PUT \/revisions\/<id>\/bundle\/ — the full-replace typed\npayload. Skills are not authored here: they come from the llma-skill store\nvia `skill_refs` and are materialized into the bundle at freeze.'
    )

/**
 * Update one `.md` file on a draft revision.
 *
 * `agent.md` writes go to the draft bundle. `skills/<id>/SKILL.md`
 * writes are store-backed — skills are materialized from the skill
 * store at freeze, so the edit publishes a new version of the
 * referenced store skill and re-pins the draft's `skill_refs` entry
 * to it. `<id>` must be a ref alias on this revision; add new skills
 * via `bundle/import/` or `skill_refs`. Tool source / schema editing
 * is out of scope here — use the per-tool endpoints. Returns the
 * updated revision so the caller can refresh in one round-trip.
 */
export const AgentApplicationsRevisionsBundleFileUpdateBody = /* @__PURE__ */ zod
    .object({
        path: zod
            .string()
            .describe(
                'Canonical bundle path. Must be `agent.md` or `skills\/<id>\/SKILL.md` where `<id>` is a skill-reference alias on this revision.'
            ),
        content: zod
            .string()
            .describe(
                'The new file contents. For `agent.md`, written verbatim to the draft bundle. For a skill, published as a new version of the referenced store skill — shared with every agent that references it. SKILL.md frontmatter (description, license, allowed-tools, metadata) is honoured when present; body-only content carries those fields forward.'
            ),
    })
    .describe(
        "Body shape for PUT \/revisions\/<id>\/bundle\/file\/.\n\nEdits one `.md` file on a draft revision. `agent.md` writes go to the\ndraft bundle. `skills\/<id>\/SKILL.md` writes are store-backed: the edit\npublishes a new version of the referenced skill-store skill and re-pins\nthe draft's `skill_refs` entry to it — skills are materialized from the\nstore at freeze, so the store is the single source of truth. Tool\nsource \/ schema editing is out of scope here; use the per-tool endpoint."
    )

/**
 * Bulk-merge a set of `.md` files into a draft revision.
 *
 * Sets `agent_md` on the draft bundle if present. `skills[]` are
 * store-backed and merge by `id`: an id already referenced by the
 * draft publishes a new version of its store skill; an unreferenced
 * id attaches the store skill of that name (publishing the payload's
 * body to it), or creates it when no such skill exists — and each
 * ref is (re-)pinned to the published version. Skills not mentioned
 * are left alone, so the import is safe to retry. Draft-only;
 * non-draft revisions return 409 untouched.
 */
export const AgentApplicationsRevisionsBundleImportCreateBody = /* @__PURE__ */ zod
    .object({
        agent_md: zod
            .string()
            .optional()
            .describe('New `agent.md` contents. When omitted, the existing agent.md is left alone.'),
        skills: zod
            .array(
                zod
                    .object({
                        id: zod
                            .string()
                            .describe(
                                'Skill id. Lowercase letters, digits, hyphens, or underscores; must start and end with `[a-z0-9]`.'
                            ),
                        description: zod
                            .string()
                            .optional()
                            .describe(
                                'One-line summary shown in the skill index. Required when creating a new skill; optional when updating one.'
                            ),
                        body: zod
                            .string()
                            .describe("The skill's markdown body, published as a new version of the store skill."),
                    })
                    .describe(
                        'One skill entry in a bulk-import payload.\n\nSkills are store-backed: each entry publishes to (or creates) a skill in\nthe skill store and pins a `skill_refs` entry on the draft. The optional\n`description` is honoured when supplied; when omitted on an existing\nskill, the current store description is preserved. Skill `id` must match\nthe canonical resource-id regex used by the janitor.'
                    )
            )
            .optional()
            .describe(
                "Per-skill payloads merged into the skill store by id and pinned onto the draft's skill references. When omitted, no skills are touched."
            ),
    })
    .describe(
        'Body shape for POST \/revisions\/<id>\/bundle\/import\/.\n\nBulk-paste hatch for migrating an existing multi-file agent. Either\n`agent_md` or `skills` (or both) may be present. Skills merge by `id`\ninto the skill store: an id already referenced by the draft publishes a\nnew version of its store skill; a new id attaches (or creates) the store\nskill of that name and appends a pinned `skill_refs` entry. Skills NOT\nmentioned are left alone — the import is safe to retry.'
    )

/**
 * Copy every file from `source_revision_id` into this revision.
 */
export const AgentApplicationsRevisionsCloneFromCreateBody = /* @__PURE__ */ zod
    .object({
        source_revision_id: zod.uuid(),
    })
    .describe(
        'Body shape for POST \/revisions\/<id>\/clone_from\/ — copy every file\nfrom `source_revision_id` into this (draft) revision.'
    )

/**
 * Fire one cron job out-of-band — the same execution path the
 * scheduler walks, but on demand. Authoring UX: the user iterates on
 * a cron prompt by clicking 'Fire now' rather than waiting for the
 * next scheduled firing. Without this, 'did my prompt do the right
 * thing?' is unanswerable until the cron actually fires.
 *
 * Idempotent via `request_id`: repeat clicks with the same id resolve
 * to the same session id rather than firing N times.
 */
export const AgentApplicationsRevisionsCronFireCreateBody = /* @__PURE__ */ zod.object({
    cron_name: zod.string().describe('`name` of the cron trigger in `spec.triggers[]` to fire.'),
    request_id: zod
        .string()
        .nullish()
        .describe(
            "Stable client-supplied id so repeated clicks of the same UI 'Fire now' button resolve to the same session id rather than firing twice. The janitor keys dedupe off `cron-manual:<rev>:<name>:<request_id>`. Omit to fire unconditionally — every call generates a fresh UUID."
        ),
})

/**
 * GET / PUT / DELETE one secret by name on this revision.
 *
 * - `GET`    → `{ key, is_set }` (never returns the value).
 * - `PUT`    → upserts `{ value }` into the env block.
 * - `DELETE` → removes the key. No-op when it wasn't set.
 *
 * Per-method scope: GET is treated as a write action so the single action
 * name maps to one consistent scope; reading whether a secret is set is
 * restricted to writers in any case.
 */
export const AgentRevisionsEnvKeysSetBody = /* @__PURE__ */ zod
    .object({
        value: zod.string(),
    })
    .describe(
        'Body shape for AgentApplicationViewSet.env_keys_set — single secret upsert.\n\nThe view merges `{KEY: value}` into the existing encrypted env block\nwithout touching other keys, so callers can set or rotate one secret\nwithout needing to read the whole block back.'
    )

/**
 * Replace this revision's encrypted env block.
 *
 * The body is `{ "env": { "<KEY>": "<value>", ... } }`. The encrypted
 * text is stored on `AgentRevision.encrypted_env`; the worker decrypts it
 * at session start via the same Fernet schedule (see
 * agent-shared/src/runtime/encryption.ts).
 */
export const AgentApplicationsRevisionsSetEnvCreateBody = /* @__PURE__ */ zod
    .object({
        env: zod.record(zod.string(), zod.string()),
    })
    .describe(
        'Body shape for AgentApplicationViewSet.set_env.\n\n`env` is a JSON object of string→string. The view encrypts it via the\nsame Fernet schedule the worker uses to decrypt.'
    )

/**
 * Full-replace the draft's store-skill references. They are resolved
 * and materialized into the bundle at freeze, not here — this only records
 * which skills (and pinned versions) the freeze should pull in.
 */
export const agentApplicationsRevisionsSkillRefsUpdateBodySkillRefsItemFromTemplateMax = 64

export const agentApplicationsRevisionsSkillRefsUpdateBodySkillRefsItemAliasMax = 64

export const agentApplicationsRevisionsSkillRefsUpdateBodySkillRefsItemAliasRegExp = new RegExp(
    '^[a-z0-9](?:[a-z0-9_-]\*[a-z0-9])?$'
)

export const AgentApplicationsRevisionsSkillRefsUpdateBody = /* @__PURE__ */ zod
    .object({
        skill_refs: zod
            .array(
                zod
                    .object({
                        from_template: zod
                            .string()
                            .max(agentApplicationsRevisionsSkillRefsUpdateBodySkillRefsItemFromTemplateMax)
                            .describe(
                                'Name of the skill in the llma-skill store to pin into this agent. Resolved at freeze to the chosen `version` and materialized into the bundle.'
                            ),
                        alias: zod
                            .string()
                            .max(agentApplicationsRevisionsSkillRefsUpdateBodySkillRefsItemAliasMax)
                            .regex(agentApplicationsRevisionsSkillRefsUpdateBodySkillRefsItemAliasRegExp)
                            .describe(
                                'Folder the resolved skill is materialized under in the bundle (`skills\/<alias>\/`). Lowercase letters, digits, hyphens or underscores, starting and ending with a letter or digit; must be unique within the revision.'
                            ),
                        version: zod
                            .number()
                            .min(1)
                            .optional()
                            .describe(
                                "Specific published version to pin. Omit to pin the store's latest version at freeze time."
                            ),
                    })
                    .describe(
                        "One reference to a versioned skill in the llma-skill store, pinned into\nthis agent's bundle at freeze."
                    )
            )
            .describe('The complete set of store-skill references for this draft; replaces any existing references.'),
    })
    .describe("Body for PUT \/revisions\/<id>\/skill_refs\/ — full-replace the draft's references.")

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const AgentApplicationsRevisionsSpecUpdateBody = /* @__PURE__ */ zod
    .object({
        spec: zod.record(zod.string(), zod.unknown()),
    })
    .describe(
        "Body shape for PUT \/revisions\/<id>\/spec\/. The body's `spec` object\nis the author-facing slice (skills\/tools are server-derived at freeze)."
    )

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const AgentApplicationsRevisionsToolsUpdateBody = /* @__PURE__ */ zod
    .object({
        description: zod.string(),
        args_schema: zod.record(zod.string(), zod.unknown()),
        source: zod.string(),
    })
    .describe('Body shape for PUT \/revisions\/<id>\/tools\/<tool_id>\/.')

/**
 * Execute one persisted custom tool in a single-shot sandbox.
 *
 * Authoring loop's "test this tool" button. The tool's source must
 * already be PUT (compiled.js is what runs); this just invokes it
 * with the caller-supplied args and a stubbed ctx. No real secrets
 * leave Django — `mock_secrets` is a `{name → placeholder}` map.
 */
export const AgentApplicationsRevisionsToolsDryRunCreateBody = /* @__PURE__ */ zod
    .object({
        args: zod
            .unknown()
            .describe(
                "Synthetic args the tool's `actions.default` is called with. Free-form JSON; the sandbox doesn't validate against the tool's `args_schema` — that's the author's responsibility to keep in sync."
            ),
        mock_secrets: zod
            .record(zod.string(), zod.string())
            .optional()
            .describe(
                'Optional `{secret_name → placeholder_string}` map. The string is returned verbatim by `ctx.secrets.ref(name)` inside the tool. The real secret value never enters the sandbox.'
            ),
    })
    .describe(
        "Body shape for POST \/revisions\/<id>\/tools\/<tool_id>\/dry_run\/.\n\nExecutes the persisted compiled.js once in the janitor's single-shot\nsandbox with caller-supplied args + a stubbed ctx. No real secrets\nleave Django — `mock_secrets` is a `{name → opaque nonce}` map the\nsandbox plumbs into `ctx.secrets.ref(name)` so the tool body returns\nsomething deterministic to the author."
    )

/**
 * Create a fresh draft revision under `application_id` and seed it
 * from `source_revision_id`. Saves the MCP one round-trip vs the
 * explicit create + clone_from sequence.
 */
export const AgentApplicationsRevisionsNewDraftCreateBody = /* @__PURE__ */ zod
    .object({
        application_id: zod.uuid(),
        source_revision_id: zod.uuid(),
    })
    .describe(
        'Body shape for POST \/revisions\/clone_from\/ — atomically create a new\ndraft revision under `application_id` and clone its initial bundle from\n`source_revision_id`. Convenience for the \"edit live\" flow so the MCP\ndoesn\'t have to do create-then-clone-from in two calls.'
    )

/**
 * Agent applications — the deployable unit of the platform.
 *
 * URLs:
 *     GET    /api/projects/<team>/agent_applications/             list
 *     POST   /api/projects/<team>/agent_applications/             create
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
 *     PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
 *     POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
 *     PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
 */
export const agentApplicationsUpdateBodyNameMax = 255

export const agentApplicationsUpdateBodySlugMax = 63

export const agentApplicationsUpdateBodySlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')

export const AgentApplicationsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentApplicationsUpdateBodyNameMax),
    slug: zod
        .string()
        .max(agentApplicationsUpdateBodySlugMax)
        .regex(agentApplicationsUpdateBodySlugRegExp)
        .optional()
        .describe(
            'Globally-unique URL identifier. Server-minted as an opaque random slug on create; only allowlisted first-party teams may set it explicitly. Slugs live in one global namespace (domain-mode ingress routing carries no team).'
        ),
    description: zod.string().optional(),
    archived: zod.boolean().optional(),
})

/**
 * Agent applications — the deployable unit of the platform.
 *
 * URLs:
 *     GET    /api/projects/<team>/agent_applications/             list
 *     POST   /api/projects/<team>/agent_applications/             create
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
 *     PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
 *     POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
 *     PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
 */
export const agentApplicationsPartialUpdateBodyNameMax = 255

export const agentApplicationsPartialUpdateBodySlugMax = 63

export const agentApplicationsPartialUpdateBodySlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')

export const AgentApplicationsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentApplicationsPartialUpdateBodyNameMax).optional(),
    slug: zod
        .string()
        .max(agentApplicationsPartialUpdateBodySlugMax)
        .regex(agentApplicationsPartialUpdateBodySlugRegExp)
        .optional()
        .describe(
            'Globally-unique URL identifier. Server-minted as an opaque random slug on create; only allowlisted first-party teams may set it explicitly. Slugs live in one global namespace (domain-mode ingress routing carries no team).'
        ),
    description: zod.string().optional(),
    archived: zod.boolean().optional(),
})

/**
 * Approve or reject a queued `agent`-type tool-approval request.
 *
 * This is the OWNER decision surface — the only PostHog-authoritative one:
 * team admins decide here, in the console. `principal`-type approvals are
 * decided by the session principal at the ingress decision API, not here.
 * The runtime side runs the tool platform-side on approve and wakes the
 * session with a synthetic tool_result either way.
 */
export const AgentApplicationsApprovalsDecideBody = /* @__PURE__ */ zod
    .object({
        decision: zod
            .enum(['approve', 'reject'])
            .describe('\* `approve` - approve\n\* `reject` - reject')
            .describe(
                "The approver's decision. `approve` runs the tool platform-side with the (possibly edited) args; `reject` records a terminal rejection and wakes the session with a synthetic rejected tool_result.\n\n\* `approve` - approve\n\* `reject` - reject"
            ),
        edited_args: zod
            .record(zod.string(), zod.unknown())
            .optional()
            .describe(
                "Approver-edited tool arguments. Only honoured when the tool's `approval_policy.allow_edit` is `true`; otherwise the janitor returns 422."
            ),
        reason: zod
            .string()
            .optional()
            .describe(
                "Free-form approver note. Surfaces in the session's synthetic tool_result so the model can communicate the reason back to the user."
            ),
    })
    .describe('Body shape for POST \/agent_applications\/<id>\/approvals\/<approval_id>\/decide\/.')

/**
 * Start a new session on this agent's LIVE (promoted) revision.
 *
 * Bridges to ingress `POST /agents/<slug>/run`, forwarding the caller's PAT
 * so the session principal is the real caller. Returns the new `session_id`;
 * drive the conversation with `agent-applications-send` and read progress with
 * `agent-applications-listen`. For non-live / draft revisions use `preview_proxy` instead.
 */
export const AgentApplicationsInvokeBody = /* @__PURE__ */ zod
    .object({
        message: zod.string().describe('The user message that starts the session. Required, non-empty.'),
        external_key: zod
            .string()
            .optional()
            .describe(
                'Optional idempotency \/ threading key. A repeat invoke with the same external_key resumes the existing session instead of starting a new one.'
            ),
    })
    .describe("Body for `agent-applications-invoke` — start a new session on the agent's live (promoted) revision.")

/**
 * Authoring-side proxy for invoking a *draft* (or any non-live) revision.
 *
 * Closes the anonymous-draft-invoke gap: the public ingress URL refuses
 * non-live invokes that don't carry the `x-agent-preview-secret` header;
 * this proxy attaches it after authenticating the Django caller.
 *
 * URL: `/api/projects/<team>/agent_applications/<app>/preview-proxy/<rest>`
 * Auth: standard PAT / session — `agents:write` scope (POST run/send/cancel
 * is a mutating invoke; the read-only `listen` GET is `agents:read`).
 */
export const AgentApplicationsPreviewProxyBody = /* @__PURE__ */ zod
    .object({
        message: zod
            .string()
            .optional()
            .describe(
                'User message to deliver to the agent. Required for `run` (starts the session) and `send` (appends to it); ignored for `cancel` \/ `listen`.'
            ),
        session_id: zod
            .string()
            .optional()
            .describe(
                'Target session id for `send` — the running session to append the message to. Omit for `run` (a fresh session is created).'
            ),
    })
    .describe(
        'Body forwarded verbatim to the agent ingress for a \*preview\* invoke of a\nnon-live revision. The meaningful shape depends on the `rest` path segment:\n\n- `run` — `{ message }`: the user message that starts a new session.\n- `send` — `{ session_id, message }`: append a message to a running session.\n- `cancel` \/ `listen` — no body.\n\nDocuments `message` \/ `session_id` so the generated MCP tool exposes them;\nany extra keys are still forwarded as-is to ingress.'
    )

/**
 * Append a message to an existing LIVE session and re-queue it.
 *
 * Bridges to ingress `POST /agents/<slug>/send`, forwarding the caller's PAT
 * so the ACL principal-match passes. A `completed` session is NOT terminal —
 * it's a per-turn idle state for a multi-turn agent, so send re-queues it for
 * another turn; only truly-terminal states (failed / cancelled / closed) 410,
 * which passes through as a 410. A janitor ownership pre-check runs first, but
 * it's redundant defense-in-depth (ingress `/send` already app-scopes the
 * load), kept for a clean early 404.
 */
export const AgentApplicationsSendBody = /* @__PURE__ */ zod
    .object({
        session_id: zod
            .uuid()
            .describe('The session to append to (returned by agent-applications-invoke). Must belong to this agent.'),
        message: zod.string().describe('The user message to append. Required, non-empty.'),
    })
    .describe('Body for `agent-applications-send` — append a message to an existing live session.')
