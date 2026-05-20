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
 * Agent applications — the deployable unit of the agent platform.
 */
export const agentApplicationsCreateBodyNameMax = 255

export const agentApplicationsCreateBodySlugMax = 63

export const agentApplicationsCreateBodySlugRegExp = new RegExp('^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$')

export const AgentApplicationsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(agentApplicationsCreateBodyNameMax)
        .describe('Human-readable display name for the application.'),
    slug: zod
        .string()
        .max(agentApplicationsCreateBodySlugMax)
        .regex(agentApplicationsCreateBodySlugRegExp)
        .describe(
            'Subdomain prefix for the application. Globally unique across all teams. Lowercase letters, digits, and hyphens only; must start and end with a letter or digit.'
        ),
    description: zod.string().optional().describe('Optional free-text description shown in the management UI.'),
})

/**
 * Agent applications — the deployable unit of the agent platform.
 */
export const agentApplicationsUpdateBodyNameMax = 255

export const agentApplicationsUpdateBodySlugMax = 63

export const agentApplicationsUpdateBodySlugRegExp = new RegExp('^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$')

export const AgentApplicationsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(agentApplicationsUpdateBodyNameMax)
        .describe('Human-readable display name for the application.'),
    slug: zod
        .string()
        .max(agentApplicationsUpdateBodySlugMax)
        .regex(agentApplicationsUpdateBodySlugRegExp)
        .describe(
            'Subdomain prefix for the application. Globally unique across all teams. Lowercase letters, digits, and hyphens only; must start and end with a letter or digit.'
        ),
    description: zod.string().optional().describe('Optional free-text description shown in the management UI.'),
})

/**
 * Agent applications — the deployable unit of the agent platform.
 */
export const agentApplicationsPartialUpdateBodyNameMax = 255

export const agentApplicationsPartialUpdateBodySlugMax = 63

export const agentApplicationsPartialUpdateBodySlugRegExp = new RegExp('^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$')

export const AgentApplicationsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(agentApplicationsPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable display name for the application.'),
    slug: zod
        .string()
        .max(agentApplicationsPartialUpdateBodySlugMax)
        .regex(agentApplicationsPartialUpdateBodySlugRegExp)
        .optional()
        .describe(
            'Subdomain prefix for the application. Globally unique across all teams. Lowercase letters, digits, and hyphens only; must start and end with a letter or digit.'
        ),
    description: zod.string().optional().describe('Optional free-text description shown in the management UI.'),
})

/**
 * v1: transitions the revision straight to state=ready.
 */
export const AgentApplicationsCompleteUploadCreateBody = /* @__PURE__ */ zod.object({
    revision_id: zod.uuid().describe('ID of the revision returned from start_deploy whose bundle has been uploaded.'),
})

/**
 * Set a revision's deployment_status to disabled. Pulls it out of any traffic role.
 */
export const AgentApplicationsDisableRevisionCreateBody = /* @__PURE__ */ zod.object({
    revision_id: zod
        .uuid()
        .describe(
            'ID of the revision to set deployment_status=disabled. Allowed from any state — use this to take a broken live or preview revision out of traffic.'
        ),
})

/**
 * PUT: replace the entire env. PATCH: merge individual keys (set to null to remove).
 */
export const agentApplicationsEnvUpdateBodyNameMax = 255

export const agentApplicationsEnvUpdateBodySlugMax = 63

export const agentApplicationsEnvUpdateBodySlugRegExp = new RegExp('^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$')

export const AgentApplicationsEnvUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(agentApplicationsEnvUpdateBodyNameMax)
        .describe('Human-readable display name for the application.'),
    slug: zod
        .string()
        .max(agentApplicationsEnvUpdateBodySlugMax)
        .regex(agentApplicationsEnvUpdateBodySlugRegExp)
        .describe(
            'Subdomain prefix for the application. Globally unique across all teams. Lowercase letters, digits, and hyphens only; must start and end with a letter or digit.'
        ),
    description: zod.string().optional().describe('Optional free-text description shown in the management UI.'),
})

/**
 * PUT: replace the entire env. PATCH: merge individual keys (set to null to remove).
 */
export const agentApplicationsEnvPartialUpdateBodyNameMax = 255

export const agentApplicationsEnvPartialUpdateBodySlugMax = 63

export const agentApplicationsEnvPartialUpdateBodySlugRegExp = new RegExp('^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$')

export const AgentApplicationsEnvPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(agentApplicationsEnvPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable display name for the application.'),
    slug: zod
        .string()
        .max(agentApplicationsEnvPartialUpdateBodySlugMax)
        .regex(agentApplicationsEnvPartialUpdateBodySlugRegExp)
        .optional()
        .describe(
            'Subdomain prefix for the application. Globally unique across all teams. Lowercase letters, digits, and hyphens only; must start and end with a letter or digit.'
        ),
    description: zod.string().optional().describe('Optional free-text description shown in the management UI.'),
})

/**
 * Mark a ready revision as preview. Blocked if required secrets are missing.
 */
export const AgentApplicationsPreviewCreateBody = /* @__PURE__ */ zod.object({
    revision_id: zod
        .uuid()
        .describe(
            'ID of the revision to mark as preview. Must be state=ready. Multiple preview revisions can coexist; no siblings are demoted.'
        ),
})

/**
 * Promote a ready revision to live. Blocked if required secrets are missing.
 */
export const AgentApplicationsPromoteCreateBody = /* @__PURE__ */ zod.object({
    revision_id: zod
        .uuid()
        .describe(
            'ID of the revision to promote. Must be state=ready. Any prior live revision on this application is atomically demoted to deployment_status=disabled.'
        ),
})

/**
 * Create a pending revision and return a presigned upload target.
 */
export const agentApplicationsStartDeployCreateBodyBundleSha256RegExp = new RegExp('^[0-9a-f]{64}$')

export const AgentApplicationsStartDeployCreateBody = /* @__PURE__ */ zod.object({
    bundle_sha256: zod
        .string()
        .regex(agentApplicationsStartDeployCreateBodyBundleSha256RegExp)
        .describe('SHA-256 of the bundle the CLI is about to upload, lowercase hex (64 chars).'),
    bundle_size: zod
        .number()
        .min(1)
        .describe('Bundle size in bytes. The presigned upload is bound to this exact size.'),
    top_level_config: zod
        .unknown()
        .describe(
            'Parsed contents of `.ass.yaml`. Validated synchronously at deploy start; bundle-level checks are deferred to the async validator when it lands.'
        ),
})
