/** Per-provider OAuth client credentials, sourced from the same env vars as Django. */
export interface ProviderCredentials {
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
    // When set, replaces the token endpoint for every kind (local/e2e mock only).
    INTEGRATION_GATEWAY_REFRESH_TOKEN_URL_OVERRIDE: string
}

/** Resolved OAuth provider config for a refreshable integration kind. */
export interface Provider {
    tokenUrl: string
    clientId: string
    clientSecret: string
}

/**
 * Resolve the OAuth provider for `kind`, or null when the kind isn't a gateway-supported OAuth2
 * provider or its client credentials aren't configured.
 *
 * Initial supported set is the generic `grant_type=refresh_token` providers (client id/secret in
 * the form body). Providers with non-standard refresh flows — Slack (DB-sourced creds), the
 * HTTP-Basic ones (reddit/pinterest/stripe), TikTok, Bing, Jira, Meta, and the service-account /
 * GitHub kinds — stay on the Django beat for now.
 */
export function providerFor(kind: string, config: ProviderCredentials): Provider | null {
    let resolved: { defaultUrl: string; clientId: string; clientSecret: string } | null = null
    switch (kind) {
        case 'hubspot':
            resolved = {
                defaultUrl: 'https://api.hubapi.com/oauth/v1/token',
                clientId: config.HUBSPOT_APP_CLIENT_ID,
                clientSecret: config.HUBSPOT_APP_CLIENT_SECRET,
            }
            break
        case 'salesforce':
            resolved = {
                defaultUrl: 'https://login.salesforce.com/services/oauth2/token',
                clientId: config.SALESFORCE_CONSUMER_KEY,
                clientSecret: config.SALESFORCE_CONSUMER_SECRET,
            }
            break
        case 'google-ads':
            resolved = {
                defaultUrl: 'https://oauth2.googleapis.com/token',
                clientId: config.GOOGLE_ADS_APP_CLIENT_ID,
                clientSecret: config.GOOGLE_ADS_APP_CLIENT_SECRET,
            }
            break
        case 'google-analytics':
            resolved = {
                defaultUrl: 'https://oauth2.googleapis.com/token',
                clientId: config.GOOGLE_ANALYTICS_APP_CLIENT_ID,
                clientSecret: config.GOOGLE_ANALYTICS_APP_CLIENT_SECRET,
            }
            break
        case 'google-search-console':
            resolved = {
                defaultUrl: 'https://oauth2.googleapis.com/token',
                clientId: config.GOOGLE_SEARCH_CONSOLE_APP_CLIENT_ID,
                clientSecret: config.GOOGLE_SEARCH_CONSOLE_APP_CLIENT_SECRET,
            }
            break
        case 'google-sheets':
            resolved = {
                defaultUrl: 'https://oauth2.googleapis.com/token',
                clientId: config.SOCIAL_AUTH_GOOGLE_OAUTH2_KEY,
                clientSecret: config.SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET,
            }
            break
        default:
            return null
    }

    if (!resolved.clientId || !resolved.clientSecret) {
        return null
    }

    return {
        tokenUrl: config.INTEGRATION_GATEWAY_REFRESH_TOKEN_URL_OVERRIDE || resolved.defaultUrl,
        clientId: resolved.clientId,
        clientSecret: resolved.clientSecret,
    }
}
