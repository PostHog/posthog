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
