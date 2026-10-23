/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface MintedDevTokenApi {
    /** Token id, used to revoke it. */
    id: string
    /** The phe_ bearer. Shown once; only its hash is stored. */
    token: string
    /**
     * Most the token can spend, in USD.
     * @pattern ^-?\d{0,8}(?:\.\d{0,2})?$
     */
    cap_usd: string
    /** When the gateway stops accepting the token. */
    expires_at: string
    /** Base URL of the AI gateway the token is valid on. */
    gateway_url: string
    /** Product the token's spend is attributed to. */
    product: string
}

export interface DevTokenRefusalApi {
    /** Stable refusal code, for example daily_limit or not_staff. */
    code: string
    /** Human-readable reason. */
    detail: string
}

export interface CliAuthorizeApi {
    /**
     * base64url SHA-256 of the CLI's PKCE code_verifier, without padding.
     * @pattern ^[A-Za-z0-9_-]{43}$
     */
    code_challenge: string
}

export interface CliAuthorizedApi {
    /** One-time code for the CLI to exchange within two minutes. */
    code: string
}

export interface CliExchangeApi {
    /**
     * Code from the authorize step.
     * @maxLength 128
     */
    code: string
    /**
     * PKCE code_verifier whose S256 challenge was authorized.
     * @pattern ^[A-Za-z0-9._~-]{43,128}$
     */
    code_verifier: string
}

export interface DevTokenRevokeApi {
    /**
     * Token to revoke. Omit to revoke all of the user's live tokens.
     * @nullable
     */
    id?: string | null
}

export interface DevTokenRevokedApi {
    /** How many tokens the gateway revoked. */
    revoked_count: number
}

/**
 * * `web` - Web
 * * `cli` - CLI
 */
export type DevTokenClientEnumApi = (typeof DevTokenClientEnumApi)[keyof typeof DevTokenClientEnumApi]

export const DevTokenClientEnumApi = {
    Web: 'web',
    Cli: 'cli',
} as const

/**
 * * `live` - Live
 * * `revoked` - Revoked
 * * `expired` - Expired
 */
export type DevTokenStatusEnumApi = (typeof DevTokenStatusEnumApi)[keyof typeof DevTokenStatusEnumApi]

export const DevTokenStatusEnumApi = {
    Live: 'live',
    Revoked: 'revoked',
    Expired: 'expired',
} as const

export interface DevTokenApi {
    /** Token id, used to revoke it. */
    id: string
    /** Where the token was minted.
     *
     * * `web` - Web
     * * `cli` - CLI */
    client: DevTokenClientEnumApi
    /**
     * Most the token can spend, in USD.
     * @pattern ^-?\d{0,8}(?:\.\d{0,2})?$
     */
    cap_usd: string
    /** When the token was minted. */
    created_at: string
    /**
     * When the gateway stops accepting the token.
     * @nullable
     */
    expires_at: string | null
    /**
     * When the token was revoked, if it was.
     * @nullable
     */
    revoked_at: string | null
    /** Whether the token still works: live, revoked or expired.
     *
     * * `live` - Live
     * * `revoked` - Revoked
     * * `expired` - Expired */
    status: DevTokenStatusEnumApi
}

export interface DevTokenUsageApi {
    /**
     * Most token caps one user can mint in 24 hours, in USD.
     * @pattern ^-?\d{0,8}(?:\.\d{0,2})?$
     */
    daily_cap_usd: string
    /**
     * Token caps the user minted in the last 24 hours, in USD.
     * @pattern ^-?\d{0,8}(?:\.\d{0,2})?$
     */
    used_usd: string
    /**
     * Cap of each new token, in USD.
     * @pattern ^-?\d{0,8}(?:\.\d{0,2})?$
     */
    token_cap_usd: string
    /** Lifetime of each new token, in seconds. */
    ttl_seconds: number
    /** Tokens the user minted in the last 24 hours, newest first, including revoked and expired ones. */
    tokens: DevTokenApi[]
}
