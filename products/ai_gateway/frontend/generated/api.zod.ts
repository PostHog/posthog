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
 * Assign one of your own unassigned personal API keys to this gateway.

An unbound key has no team boundary, so only its owner may assign it — hence
the user filter (unlike bind_credential, which moves the team's already-bound keys).
 */
export const GatewaysAssignCredentialCreateBody = /* @__PURE__ */ zod.object({
    credential_id: zod
        .string()
        .describe('Id of one of your own unassigned personal API keys to assign to this gateway.'),
})

/**
 * Reassign a credential to this gateway.

Only credentials already bound to one of this team's gateways can be moved —
this manages attribution across the team's own gateways, not arbitrary keys.
 */
export const GatewaysBindCredentialCreateBody = /* @__PURE__ */ zod.object({
    credential_type: zod
        .enum(['personal_api_key', 'oauth_application'])
        .describe('\* `personal_api_key` - personal_api_key\n\* `oauth_application` - oauth_application')
        .describe(
            'Which kind of credential to reassign.\n\n\* `personal_api_key` - personal_api_key\n\* `oauth_application` - oauth_application'
        ),
    credential_id: zod.string().describe('Id of the credential to reassign to this gateway.'),
})
