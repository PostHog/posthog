import { ProviderCredentials, providerFor } from './providers'

function creds(overrides: Partial<ProviderCredentials> = {}): ProviderCredentials {
    return {
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
        INTEGRATION_GATEWAY_REFRESH_TOKEN_URL_OVERRIDE: '',
        ...overrides,
    }
}

describe('providerFor', () => {
    // Kinds with non-standard refresh flows must stay on the Django beat, even with creds present.
    it.each(['slack', 'github', 'stripe', 'reddit-ads', 'tiktok-ads'])(
        'returns null for unsupported kind %s',
        (kind) => {
            expect(providerFor(kind, creds({ HUBSPOT_APP_CLIENT_ID: 'x', HUBSPOT_APP_CLIENT_SECRET: 'y' }))).toBeNull()
        }
    )

    it('returns null when a supported kind has no configured credentials', () => {
        expect(providerFor('hubspot', creds())).toBeNull()
    })

    it('resolves a configured kind to its default token url', () => {
        expect(
            providerFor('hubspot', creds({ HUBSPOT_APP_CLIENT_ID: 'cid', HUBSPOT_APP_CLIENT_SECRET: 'sec' }))
        ).toEqual({ tokenUrl: 'https://api.hubapi.com/oauth/v1/token', clientId: 'cid', clientSecret: 'sec' })
    })

    it('maps google-sheets to the shared social-auth google credentials', () => {
        expect(
            providerFor(
                'google-sheets',
                creds({ SOCIAL_AUTH_GOOGLE_OAUTH2_KEY: 'gk', SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET: 'gs' })
            )
        ).toEqual({ tokenUrl: 'https://oauth2.googleapis.com/token', clientId: 'gk', clientSecret: 'gs' })
    })

    it('applies the token url override (local/e2e) over the default', () => {
        const provider = providerFor(
            'hubspot',
            creds({
                HUBSPOT_APP_CLIENT_ID: 'cid',
                HUBSPOT_APP_CLIENT_SECRET: 'sec',
                INTEGRATION_GATEWAY_REFRESH_TOKEN_URL_OVERRIDE: 'http://localhost:9999/token',
            })
        )
        expect(provider?.tokenUrl).toBe('http://localhost:9999/token')
    })
})
