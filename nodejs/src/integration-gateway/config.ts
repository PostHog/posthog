export function splitCsv(raw: string): string[] {
    return raw
        .split(',')
        .map((s) => s.trim())
        .filter((s) => s.length > 0)
}

/** Which teams the gateway owns refresh for. `*` = all teams; otherwise an explicit id allowlist. */
export type RefreshTeamGate = '*' | Set<number>

/**
 * Parse `INTEGRATION_GATEWAY_REFRESH_TEAMS`. Deliberately only `*` or explicit ids (no percentage
 * rollout): refresh ownership must be a deterministic, stable partition between the gateway and
 * Django's beat — a row flipping owners call-to-call would leave gaps. Empty => own no teams.
 */
export function parseRefreshTeams(raw: string): RefreshTeamGate {
    const parts = splitCsv(raw)
    if (parts.includes('*')) {
        return '*'
    }
    return new Set(parts.map((p) => parseInt(p, 10)).filter((n) => Number.isInteger(n)))
}

/**
 * Integration-gateway-specific config. The generic infra fields it also needs
 * (ENCRYPTION_SALT_KEYS, DATABASE_URL, REDIS_URL, HTTP_SERVER_PORT, ...) already live in
 * CommonConfig and arrive via the base `defaultConfig` spread in the server.
 */
export type IntegrationGatewayConfig = {
    INTEGRATION_GATEWAY_CACHE_TTL_SECONDS: number
    INTEGRATION_GATEWAY_CACHE_MAX_CAPACITY: number
    INTEGRATION_GATEWAY_MAX_BATCH_SIZE: number

    // Token refresh (writer). A row is refreshed by the gateway only when its kind is in
    // REFRESH_KINDS (capability contract, shared with Django) AND its team is in REFRESH_TEAMS
    // (rollout gate). Either empty => gateway never refreshes it and Django's beat owns it.
    INTEGRATION_GATEWAY_REFRESH_KINDS: string
    INTEGRATION_GATEWAY_REFRESH_TEAMS: string
    INTEGRATION_GATEWAY_REFRESH_LOCK_TTL_SECONDS: number
    INTEGRATION_GATEWAY_REFRESH_HTTP_TIMEOUT_MS: number
    INTEGRATION_GATEWAY_REFRESH_TOKEN_URL_OVERRIDE: string

    // Per-provider OAuth client credentials, sharing env var names with posthog/settings/integrations.py.
    HUBSPOT_APP_CLIENT_ID: string
    HUBSPOT_APP_CLIENT_SECRET: string
    SALESFORCE_CONSUMER_KEY: string
    SALESFORCE_CONSUMER_SECRET: string
    GOOGLE_ADS_APP_CLIENT_ID: string
    GOOGLE_ADS_APP_CLIENT_SECRET: string
    GOOGLE_ANALYTICS_APP_CLIENT_ID: string
    GOOGLE_ANALYTICS_APP_CLIENT_SECRET: string
    GOOGLE_SEARCH_CONSOLE_APP_CLIENT_ID: string
    GOOGLE_SEARCH_CONSOLE_APP_CLIENT_SECRET: string
    SOCIAL_AUTH_GOOGLE_OAUTH2_KEY: string
    SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET: string
}

export function getDefaultIntegrationGatewayConfig(): IntegrationGatewayConfig {
    return {
        INTEGRATION_GATEWAY_CACHE_TTL_SECONDS: 30,
        INTEGRATION_GATEWAY_CACHE_MAX_CAPACITY: 50000,
        INTEGRATION_GATEWAY_MAX_BATCH_SIZE: 100,

        INTEGRATION_GATEWAY_REFRESH_KINDS: '',
        INTEGRATION_GATEWAY_REFRESH_TEAMS: '',
        INTEGRATION_GATEWAY_REFRESH_LOCK_TTL_SECONDS: 30,
        INTEGRATION_GATEWAY_REFRESH_HTTP_TIMEOUT_MS: 10000,
        INTEGRATION_GATEWAY_REFRESH_TOKEN_URL_OVERRIDE: '',

        HUBSPOT_APP_CLIENT_ID: '',
        HUBSPOT_APP_CLIENT_SECRET: '',
        SALESFORCE_CONSUMER_KEY: '',
        SALESFORCE_CONSUMER_SECRET: '',
        GOOGLE_ADS_APP_CLIENT_ID: '',
        GOOGLE_ADS_APP_CLIENT_SECRET: '',
        GOOGLE_ANALYTICS_APP_CLIENT_ID: '',
        GOOGLE_ANALYTICS_APP_CLIENT_SECRET: '',
        GOOGLE_SEARCH_CONSOLE_APP_CLIENT_ID: '',
        GOOGLE_SEARCH_CONSOLE_APP_CLIENT_SECRET: '',
        SOCIAL_AUTH_GOOGLE_OAUTH2_KEY: '',
        SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET: '',
    }
}
