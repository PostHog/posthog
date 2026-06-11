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

export const gatewaysCreateBodySlugMax = 64

export const GatewaysCreateBody = /* @__PURE__ */ zod.object({
    slug: zod
        .string()
        .max(gatewaysCreateBodySlugMax)
        .describe(
            "Lowercase, URL-safe identifier (letters, digits, '-' or '_', no leading\/trailing separator). This is the $ai_gateway_slug billing-attribution value the LLM gateway records for every request a bound credential makes."
        ),
})

export const gatewaysUpdateBodySlugMax = 64

export const GatewaysUpdateBody = /* @__PURE__ */ zod.object({
    slug: zod
        .string()
        .max(gatewaysUpdateBodySlugMax)
        .describe(
            "Lowercase, URL-safe identifier (letters, digits, '-' or '_', no leading\/trailing separator). This is the $ai_gateway_slug billing-attribution value the LLM gateway records for every request a bound credential makes."
        ),
})

export const gatewaysPartialUpdateBodySlugMax = 64

export const GatewaysPartialUpdateBody = /* @__PURE__ */ zod.object({
    slug: zod
        .string()
        .max(gatewaysPartialUpdateBodySlugMax)
        .optional()
        .describe(
            "Lowercase, URL-safe identifier (letters, digits, '-' or '_', no leading\/trailing separator). This is the $ai_gateway_slug billing-attribution value the LLM gateway records for every request a bound credential makes."
        ),
})

/**
 * Assign one of the team's unassigned project secret keys to this gateway (admin-only).

The key must belong to the gateway's canonical team, so a key from another
project can't be attributed here.
 */
export const GatewaysAssignCredentialCreateBody = /* @__PURE__ */ zod.object({
    credential_id: zod
        .string()
        .describe("Id of one of the team's unassigned project secret keys to assign to this gateway."),
})

/**
 * Remove a credential from this gateway, leaving it unassigned (admin-only).
 */
export const GatewaysUnassignCredentialCreateBody = /* @__PURE__ */ zod.object({
    credential_type: zod
        .enum(['project_secret_api_key', 'oauth_application'])
        .describe('\* `project_secret_api_key` - project_secret_api_key\n\* `oauth_application` - oauth_application')
        .describe(
            'Which kind of credential to unassign.\n\n\* `project_secret_api_key` - project_secret_api_key\n\* `oauth_application` - oauth_application'
        ),
    credential_id: zod.string().describe('Id of the credential to unassign from this gateway.'),
})
