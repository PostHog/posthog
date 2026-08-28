import { ConfigScopeEnumApi, IdentityProviderConfigApi } from '~/generated/core/api.schemas'

import { getIdentityProviderConfigForScope, getIdentityProviderConfigStatus } from './identityProviderConfigUtils'

const makeConfig = (overrides: Partial<IdentityProviderConfigApi> = {}): IdentityProviderConfigApi => ({
    id: 'config-id',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    has_saml: false,
    saml_relay_state: 'relay-state',
    has_scim: false,
    scim_base_url: 'https://example.com/scim/v2/config-id',
    scim_bearer_token: null,
    has_id_jag: false,
    ...overrides,
})

describe('identityProviderConfigUtils', () => {
    it('prefers a feature-scoped config and falls back to an unscoped config', () => {
        const unscopedConfig = makeConfig({ id: 'unscoped', config_scope: null })
        const samlConfig = makeConfig({ id: 'saml', config_scope: ConfigScopeEnumApi.Saml })

        expect(getIdentityProviderConfigForScope([unscopedConfig, samlConfig], ConfigScopeEnumApi.Saml)?.id).toBe(
            'saml'
        )
        expect(getIdentityProviderConfigForScope([unscopedConfig, samlConfig], ConfigScopeEnumApi.Scim)?.id).toBe(
            'unscoped'
        )
    })

    it.each([
        ['complete SAML', ConfigScopeEnumApi.Saml, makeConfig({ has_saml: true }), 'configured'],
        [
            'partial SAML',
            ConfigScopeEnumApi.Saml,
            makeConfig({ saml_entity_id: 'https://idp.example.com' }),
            'partially_configured',
        ],
        ['enabled SCIM', ConfigScopeEnumApi.Scim, makeConfig({ has_scim: true }), 'configured'],
        [
            'partial XAA',
            ConfigScopeEnumApi.Xaa,
            makeConfig({ id_jag_allowed_clients: ['client-id'] }),
            'partially_configured',
        ],
        ['missing config', ConfigScopeEnumApi.Xaa, undefined, 'not_configured'],
    ] as const)('reports the status for %s', (_, configScope, config, expectedStatus) => {
        expect(getIdentityProviderConfigStatus(config, configScope)).toBe(expectedStatus)
    })
})
