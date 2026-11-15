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
 * @summary Authorize a CLI login by its PKCE challenge
 */
export const aiGatewayDevTokensCliAuthorizeCreateBodyCodeChallengeRegExp = new RegExp('^[A-Za-z0-9_-]{43}$')

export const AiGatewayDevTokensCliAuthorizeCreateBody = /* @__PURE__ */ zod.object({
    code_challenge: zod
        .string()
        .regex(aiGatewayDevTokensCliAuthorizeCreateBodyCodeChallengeRegExp)
        .describe("base64url SHA-256 of the CLI's PKCE code_verifier, without padding."),
})

/**
 * @summary Exchange a CLI authorization code for a developer mode token
 */
export const aiGatewayDevTokensCliExchangeCreateBodyCodeMax = 128

export const aiGatewayDevTokensCliExchangeCreateBodyCodeVerifierRegExp = new RegExp('^[A-Za-z0-9._~-]{43,128}$')

export const AiGatewayDevTokensCliExchangeCreateBody = /* @__PURE__ */ zod.object({
    code: zod.string().max(aiGatewayDevTokensCliExchangeCreateBodyCodeMax).describe('Code from the authorize step.'),
    code_verifier: zod
        .string()
        .regex(aiGatewayDevTokensCliExchangeCreateBodyCodeVerifierRegExp)
        .describe('PKCE code_verifier whose S256 challenge was authorized.'),
})

/**
 * @summary Revoke one or all of your developer mode tokens
 */
export const AiGatewayDevTokensRevokeCreateBody = /* @__PURE__ */ zod.object({
    id: zod.uuid().nullish().describe("Token to revoke. Omit to revoke all of the user's live tokens."),
})

/**
 * @summary Look up a developer mode token's status and budget left by its bearer
 */
export const aiGatewayDevTokensTokenStatusCreateBodyTokenRegExp = new RegExp('^phe_[A-Za-z0-9_-]{1,252}$')

export const AiGatewayDevTokensTokenStatusCreateBody = /* @__PURE__ */ zod.object({
    token: zod
        .string()
        .regex(aiGatewayDevTokensTokenStatusCreateBodyTokenRegExp)
        .describe('The phe_ bearer to look up. Only its sha256 is compared.'),
})
