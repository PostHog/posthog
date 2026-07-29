import { isDevEnv, isTestEnv } from '~/common/utils/env-utils'

/** Shared secret used only for local dev + tests so the whole flow works out of the box. */
export const LOCAL_DEV_INTEGRATION_GATEWAY_JWT_SECRET = 'integration-gateway-dev-secret'

export function splitCsv(raw: string): string[] {
    return raw
        .split(',')
        .map((s) => s.trim())
        .filter((s) => s.length > 0)
}

/**
 * Integration-gateway-specific config. The generic infra fields it also needs
 * (ENCRYPTION_SALT_KEYS, DATABASE_URL, REDIS_URL, HTTP_SERVER_PORT, ...) already live in
 * CommonConfig and arrive via the base `defaultConfig` spread in the server.
 */
export type IntegrationGatewayConfig = {
    // Legacy decrypt-only key material (values written before the ENCRYPTION_SALT_KEYS rework).
    SECRET_KEY: string
    SECRET_KEY_FALLBACKS: string
    SALT_KEY: string

    // Scoped-JWT verification secret(s) for callers (newest first). Empty in prod => reject all.
    INTEGRATION_GATEWAY_JWT_SECRET: string
    INTEGRATION_GATEWAY_JWT_SECRET_FALLBACKS: string

    INTEGRATION_GATEWAY_CACHE_TTL_SECONDS: number
    INTEGRATION_GATEWAY_CACHE_MAX_CAPACITY: number
    INTEGRATION_GATEWAY_MAX_BATCH_SIZE: number

    // Token refresh (writer). Empty kinds => gateway never refreshes (Django's beat owns it).
    INTEGRATION_GATEWAY_REFRESH_KINDS: string
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
    const devOrTest = isDevEnv() || isTestEnv()
    return {
        SECRET_KEY: '',
        SECRET_KEY_FALLBACKS: '',
        SALT_KEY: '0123456789abcdefghijklmnopqrstuvwxyz',

        INTEGRATION_GATEWAY_JWT_SECRET: devOrTest ? LOCAL_DEV_INTEGRATION_GATEWAY_JWT_SECRET : '',
        INTEGRATION_GATEWAY_JWT_SECRET_FALLBACKS: '',

        INTEGRATION_GATEWAY_CACHE_TTL_SECONDS: 30,
        INTEGRATION_GATEWAY_CACHE_MAX_CAPACITY: 50000,
        INTEGRATION_GATEWAY_MAX_BATCH_SIZE: 100,

        INTEGRATION_GATEWAY_REFRESH_KINDS: '',
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
