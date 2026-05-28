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

URLs:
    GET    /api/projects/<team>/agent_applications/             list
    POST   /api/projects/<team>/agent_applications/             create
    GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
    PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
    DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/   set env
 */
export const agentApplicationsCreateBodyNameMax = 255

export const agentApplicationsCreateBodySlugMax = 63

export const agentApplicationsCreateBodyArchivedDefault = false

export const AgentApplicationsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentApplicationsCreateBodyNameMax),
    slug: zod.string().max(agentApplicationsCreateBodySlugMax),
    description: zod.string().optional(),
    archived: zod.boolean().default(agentApplicationsCreateBodyArchivedDefault),
})

/**
 * Revisions of an agent. Created in `draft`, promoted through
`ready → live` once the bundle has been uploaded + frozen.

URLs (nested under an application):

    Model CRUD:
        GET   .../revisions/                       list
        POST  .../revisions/                       create draft
        GET   .../revisions/<id>/                  retrieve
        PATCH .../revisions/<id>/                  update spec (draft only)

    Lifecycle:
        POST  .../revisions/<id>/promote/          ready → live
        POST  .../revisions/<id>/archive/          → archived
        POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
        POST  .../revisions/<id>/clone_from/       copy bundle from another rev
        POST  .../revisions/new_draft/             create draft + clone_from atomically

    Bundle authoring (proxied to the janitor):
        GET    .../revisions/<id>/manifest/        list paths + sha256
        GET    .../revisions/<id>/file/?path=…     read one file
        PUT    .../revisions/<id>/file/?path=…     write one file (draft)
        DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
        GET    .../revisions/<id>/bundle/          bulk pull all files
        PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const agentApplicationsRevisionsCreateBodyBundleUriDefault = ``

export const AgentApplicationsRevisionsCreateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsCreateBodyBundleUriDefault),
    spec: zod.unknown().optional(),
})

/**
 * Spec edits are only allowed while state='draft'. Once promoted to
ready/live the spec is frozen — change requires a new revision.
 */
export const agentApplicationsRevisionsUpdateBodyBundleUriDefault = ``

export const AgentApplicationsRevisionsUpdateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsUpdateBodyBundleUriDefault),
    spec: zod.unknown().optional(),
})

/**
 * Revisions of an agent. Created in `draft`, promoted through
`ready → live` once the bundle has been uploaded + frozen.

URLs (nested under an application):

    Model CRUD:
        GET   .../revisions/                       list
        POST  .../revisions/                       create draft
        GET   .../revisions/<id>/                  retrieve
        PATCH .../revisions/<id>/                  update spec (draft only)

    Lifecycle:
        POST  .../revisions/<id>/promote/          ready → live
        POST  .../revisions/<id>/archive/          → archived
        POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
        POST  .../revisions/<id>/clone_from/       copy bundle from another rev
        POST  .../revisions/new_draft/             create draft + clone_from atomically

    Bundle authoring (proxied to the janitor):
        GET    .../revisions/<id>/manifest/        list paths + sha256
        GET    .../revisions/<id>/file/?path=…     read one file
        PUT    .../revisions/<id>/file/?path=…     write one file (draft)
        DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
        GET    .../revisions/<id>/bundle/          bulk pull all files
        PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const agentApplicationsRevisionsPartialUpdateBodyBundleUriDefault = ``

export const AgentApplicationsRevisionsPartialUpdateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsPartialUpdateBodyBundleUriDefault),
    spec: zod.unknown().optional(),
})

/**
 * Mark a revision archived. If it was the live one, clear the
application's live_revision pointer (the app effectively has no
deployable version until another revision is promoted).
 */
export const agentApplicationsRevisionsArchiveCreateBodyBundleUriDefault = ``

export const AgentApplicationsRevisionsArchiveCreateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsArchiveCreateBodyBundleUriDefault),
    spec: zod.unknown().optional(),
})

/**
 * Bulk-push the bundle. Body `{ files, mode: replace|merge }`.
 */
export const agentApplicationsRevisionsBundleUpdateBodyBundleUriDefault = ``

export const AgentApplicationsRevisionsBundleUpdateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsBundleUpdateBodyBundleUriDefault),
    spec: zod.unknown().optional(),
})

/**
 * Copy every file from `source_revision_id` into this revision.
 */
export const agentApplicationsRevisionsCloneFromCreateBodyBundleUriDefault = ``

export const AgentApplicationsRevisionsCloneFromCreateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsCloneFromCreateBodyBundleUriDefault),
    spec: zod.unknown().optional(),
})

/**
 * Write one file by `?path=...`. Draft-only (janitor enforces).
 */
export const agentApplicationsRevisionsFileUpdateBodyBundleUriDefault = ``

export const AgentApplicationsRevisionsFileUpdateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsFileUpdateBodyBundleUriDefault),
    spec: zod.unknown().optional(),
})

/**
 * Freeze the bundle: draft → ready, stamps sha256 on the row.
The janitor computes the digest and updates the revision row in PG;
Django re-reads the row before returning so the response reflects
the persisted state.
 */
export const agentApplicationsRevisionsFreezeCreateBodyBundleUriDefault = ``

export const AgentApplicationsRevisionsFreezeCreateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsFreezeCreateBodyBundleUriDefault),
    spec: zod.unknown().optional(),
})

/**
 * ready → live. Sets the parent application's live_revision.
 */
export const agentApplicationsRevisionsPromoteCreateBodyBundleUriDefault = ``

export const AgentApplicationsRevisionsPromoteCreateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsPromoteCreateBodyBundleUriDefault),
    spec: zod.unknown().optional(),
})

/**
 * Create a fresh draft revision under `application_id` and seed it
from `source_revision_id`. Saves the MCP one round-trip vs the
explicit create + clone_from sequence.
 */
export const agentApplicationsRevisionsNewDraftCreateBodyBundleUriDefault = ``

export const AgentApplicationsRevisionsNewDraftCreateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsNewDraftCreateBodyBundleUriDefault),
    spec: zod.unknown().optional(),
})

/**
 * Agent applications — the deployable unit of the platform.

URLs:
    GET    /api/projects/<team>/agent_applications/             list
    POST   /api/projects/<team>/agent_applications/             create
    GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
    PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
    DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/   set env
 */
export const agentApplicationsUpdateBodyNameMax = 255

export const agentApplicationsUpdateBodySlugMax = 63

export const agentApplicationsUpdateBodyArchivedDefault = false

export const AgentApplicationsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentApplicationsUpdateBodyNameMax),
    slug: zod.string().max(agentApplicationsUpdateBodySlugMax),
    description: zod.string().optional(),
    archived: zod.boolean().default(agentApplicationsUpdateBodyArchivedDefault),
})

/**
 * Agent applications — the deployable unit of the platform.

URLs:
    GET    /api/projects/<team>/agent_applications/             list
    POST   /api/projects/<team>/agent_applications/             create
    GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
    PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
    DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/   set env
 */
export const agentApplicationsPartialUpdateBodyNameMax = 255

export const agentApplicationsPartialUpdateBodySlugMax = 63

export const agentApplicationsPartialUpdateBodyArchivedDefault = false

export const AgentApplicationsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentApplicationsPartialUpdateBodyNameMax).optional(),
    slug: zod.string().max(agentApplicationsPartialUpdateBodySlugMax).optional(),
    description: zod.string().optional(),
    archived: zod.boolean().default(agentApplicationsPartialUpdateBodyArchivedDefault),
})

/**
 * Replace the agent's encrypted env block.

The body is `{ "env": { "<KEY>": "<value>", ... } }`. The encrypted
text gets stored on AgentApplication.encrypted_env; the worker
decrypts it at session start via the same Fernet schedule (see
agent-shared/src/runtime/encryption.ts).
 */
export const agentApplicationsSetEnvCreateBodyNameMax = 255

export const agentApplicationsSetEnvCreateBodySlugMax = 63

export const agentApplicationsSetEnvCreateBodyArchivedDefault = false

export const AgentApplicationsSetEnvCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentApplicationsSetEnvCreateBodyNameMax),
    slug: zod.string().max(agentApplicationsSetEnvCreateBodySlugMax),
    description: zod.string().optional(),
    archived: zod.boolean().default(agentApplicationsSetEnvCreateBodyArchivedDefault),
})
