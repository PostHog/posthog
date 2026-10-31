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

export interface DevUserUsageApi {
    /**
     * PostHog user id. Null when no user has this distinct_id.
     * @nullable
     */
    user_id: number | null
    /**
     * The user's email. Null when no user has this distinct_id.
     * @nullable
     */
    email: string | null
    /** distinct_id pinned on the user's tokens as $ai_user. */
    distinct_id: string
    /** Tokens minted in the last 24 hours. */
    tokens_minted_24h: number
    /** Tokens minted in the last 30 days. */
    tokens_minted_30d: number
    /** Tokens that are neither revoked nor expired. */
    live_tokens: number
    /** Tokens minted in the last 30 days that were revoked. */
    revoked_30d: number
    /**
     * Token caps minted in the last 24 hours, in USD.
     * @pattern ^-?\d{0,8}(?:\.\d{0,2})?$
     */
    reserved_usd_24h: string
    /**
     * Settled gateway spend in the last 24 hours, in USD.
     * @pattern ^-?\d{0,6}(?:\.\d{0,6})?$
     */
    spend_usd_24h: string
    /**
     * Settled gateway spend in the last 7 days, in USD.
     * @pattern ^-?\d{0,6}(?:\.\d{0,6})?$
     */
    spend_usd_7d: string
    /**
     * Settled gateway spend in the last 30 days, in USD.
     * @pattern ^-?\d{0,6}(?:\.\d{0,6})?$
     */
    spend_usd_30d: string
    /**
     * When the user last minted a token.
     * @nullable
     */
    last_minted_at: string | null
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

export interface DevTokenActivityApi {
    /** When the action happened. */
    at: string
    /** What happened to the token: minted or revoked. */
    activity: string
    /**
     * Who did it. Null when the user was deleted.
     * @nullable
     */
    actor_email: string | null
    /**
     * Whose token it is. Null when the token row is gone, e.g. a refused mint.
     * @nullable
     */
    owner_email: string | null
    /** Where the token was minted.
     *
     * * `web` - Web
     * * `cli` - CLI */
    client: DevTokenClientEnumApi | null
    /**
     * Most the token can spend, in USD.
     * @nullable
     * @pattern ^-?\d{0,8}(?:\.\d{0,2})?$
     */
    cap_usd: string | null
}

export interface DevTeamUsageApi {
    /** Project whose wallet pays for developer mode tokens. */
    paying_team_id: number
    /** One row per user with tokens or spend, highest spend first. */
    users: DevUserUsageApi[]
    /** Mints and revokes in the last 30 days, newest first, at most 1000. */
    activity: DevTokenActivityApi[]
}

export interface DevTokenStatusRequestApi {
    /**
     * The phe_ bearer to look up. Only its sha256 is compared.
     * @pattern ^phe_[A-Za-z0-9_-]{1,252}$
     */
    token: string
}

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
    /**
     * Budget left on a live token, net of in-flight requests, in USD. Null when not live or unknown.
     * @nullable
     * @pattern ^-?\d{0,6}(?:\.\d{0,6})?$
     */
    remaining_usd: string | null
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
