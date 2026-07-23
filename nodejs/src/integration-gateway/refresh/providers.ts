import { isProdEnv } from '~/common/utils/env-utils'

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
    // Local/e2e mock hook only. Ignored in production (see providerFor) so a misconfigured
    // deployment can never redirect real credential traffic to an arbitrary host.
    INTEGRATION_GATEWAY_REFRESH_TOKEN_URL_OVERRIDE: string
}

/** Resolved OAuth provider config for a refreshable integration kind. */
export interface Provider {
    tokenUrl: string
    clientId: string
    clientSecret: string
}

const SALESFORCE_LOGIN_TOKEN_URL = 'https://login.salesforce.com/services/oauth2/token'

/**
 * Resolve the Salesforce token endpoint from the integration's stored `instance_url`, mirroring
 * Django's `_salesforce_instance_host`: a sandbox/My-Domain org must refresh against its own host,
 * and the prod login URL would refuse a sandbox-issued refresh_token. Validated conservatively
 * (https only, no port/userinfo, hostname under salesforce.com); anything else falls back to the
 * prod login URL.
 */
function salesforceTokenUrl(instanceUrl: unknown): string {
    if (typeof instanceUrl !== 'string' || !instanceUrl) {
        return SALESFORCE_LOGIN_TOKEN_URL
    }
    let url: URL
    try {
        url = new URL(instanceUrl)
    } catch {
        return SALESFORCE_LOGIN_TOKEN_URL
    }
    if (url.protocol !== 'https:' || url.port || url.username || url.password) {
        return SALESFORCE_LOGIN_TOKEN_URL
    }
    if (url.hostname !== 'salesforce.com' && !url.hostname.endsWith('.salesforce.com')) {
        return SALESFORCE_LOGIN_TOKEN_URL
    }
    return `https://${url.hostname}/services/oauth2/token`
}

/**
 * Resolve the OAuth provider for `kind`, or null when the kind isn't a gateway-supported OAuth2
 * provider or its client credentials aren't configured. `integrationConfig` is the row's plaintext
 * `config` (used for Salesforce's per-org instance host).
 *
 * Initial supported set is the generic `grant_type=refresh_token` providers (client id/secret in
 * the form body). Providers with non-standard refresh flows — Slack (DB-sourced creds), the
 * HTTP-Basic ones (reddit/pinterest/stripe), TikTok, Bing, Jira, Meta, and the service-account /
 * GitHub kinds — stay on the Django beat for now.
 */
export function providerFor(
    kind: string,
    config: ProviderCredentials,
    integrationConfig: Record<string, any> = {}
): Provider | null {
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
                // Sandbox/My-Domain orgs must refresh at their own instance host (Django parity).
                defaultUrl: salesforceTokenUrl(integrationConfig.instance_url),
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

    // The override exists purely for local/e2e mocking; ignore it in production so a misconfigured
    // deployment fails closed instead of POSTing client secrets + refresh tokens to an arbitrary host.
    const override = config.INTEGRATION_GATEWAY_REFRESH_TOKEN_URL_OVERRIDE
    const tokenUrl = override && !isProdEnv() ? override : resolved.defaultUrl

    return {
        tokenUrl,
        clientId: resolved.clientId,
        clientSecret: resolved.clientSecret,
    }
}
