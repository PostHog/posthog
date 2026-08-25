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

export const aiGatewayUserSpendLimitCreateBodyLimitUsdRegExp = new RegExp('^-?\\d{0,13}(?:\\.\\d{0,6})?$')
export const aiGatewayUserSpendLimitCreateBodyWindowSecondsMin = 3600
export const aiGatewayUserSpendLimitCreateBodyWindowSecondsMax = 31622400

export const AiGatewayUserSpendLimitCreateBody = /* @__PURE__ */ zod.object({
    limit_usd: zod
        .stringFormat('decimal', aiGatewayUserSpendLimitCreateBodyLimitUsdRegExp)
        .describe(
            'The limit in USD. The gateway stores the limit and, once enforcement is live for this traffic, refuses spend past it until the window resets.'
        ),
    window_seconds: zod
        .number()
        .min(aiGatewayUserSpendLimitCreateBodyWindowSecondsMin)
        .max(aiGatewayUserSpendLimitCreateBodyWindowSecondsMax)
        .describe(
            'Length of the accounting window the limit applies to, in seconds. The window is fixed rather than sliding: it starts at the first spend after a reset and the counter resets once per window. At least an hour and at most 366 days.'
        ),
})
