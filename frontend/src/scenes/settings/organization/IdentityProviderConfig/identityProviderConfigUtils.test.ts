import { ConfigScopeEnumApi, DomainScopeEnumApi, IdentityProviderConfigApi } from '~/generated/core/api.schemas'

import {
    getIdentityProviderConfigForScope,
    getIdentityProviderConfigsForScope,
    getIdentityProviderConfigStatus,
    hasSamlDomainScopeConflict,
    getIdentityProviderConfigStatusDescription,
} from './identityProviderConfigUtils'

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
    it('returns every config for a feature while keeping legacy unscoped fallback behavior', () => {
        const firstSamlConfig = makeConfig({ id: 'saml-1', config_scope: ConfigScopeEnumApi.Saml })
        const secondSamlConfig = makeConfig({ id: 'saml-2', config_scope: ConfigScopeEnumApi.Saml })
        expect(
            getIdentityProviderConfigsForScope([firstSamlConfig, secondSamlConfig], ConfigScopeEnumApi.Saml)
        ).toEqual([firstSamlConfig, secondSamlConfig])

        const unscopedConfig = makeConfig({ id: 'unscoped', config_scope: null })
        const samlConfig = makeConfig({ id: 'saml', config_scope: ConfigScopeEnumApi.Saml })

        expect(getIdentityProviderConfigForScope([unscopedConfig, samlConfig], ConfigScopeEnumApi.Saml)?.id).toBe(
            'saml'
        )
        expect(getIdentityProviderConfigForScope([unscopedConfig, samlConfig], ConfigScopeEnumApi.Scim)?.id).toBe(
            'unscoped'
        )
        expect(getIdentityProviderConfigsForScope([unscopedConfig, samlConfig], ConfigScopeEnumApi.Scim)).toEqual([
            unscopedConfig,
        ])
    })

    it.each([
        [
            'all-domain configuration overlapping a selected-domain configuration',
            DomainScopeEnumApi.All,
            [],
            ['domain-1'],
            [
                makeConfig({ id: 'current', has_saml: true }),
                makeConfig({
                    id: 'other',
                    config_scope: ConfigScopeEnumApi.Saml,
                    organization_domain_ids: ['domain-1'],
                    has_saml: true,
                }),
            ],
            true,
        ],
        [
            'selected-domain configuration overlapping an all-domain configuration',
            DomainScopeEnumApi.Selected,
            ['domain-1'],
            ['domain-1'],
            [
                makeConfig({ id: 'current', has_saml: true }),
                makeConfig({
                    id: 'other',
                    config_scope: ConfigScopeEnumApi.Saml,
                    domain_scope: DomainScopeEnumApi.All,
                    has_saml: true,
                }),
            ],
            true,
        ],
        [
            'selected-domain configuration with no overlapping domains',
            DomainScopeEnumApi.Selected,
            ['domain-1'],
            ['domain-1', 'domain-2'],
            [
                makeConfig({ id: 'current', has_saml: true }),
                makeConfig({
                    id: 'other',
                    config_scope: ConfigScopeEnumApi.Saml,
                    organization_domain_ids: ['domain-2'],
                    has_saml: true,
                }),
            ],
            false,
        ],
    ] as const)('detects %s', (_, domainScope, selectedDomainIds, verifiedDomainIds, configs, expected) => {
        expect(hasSamlDomainScopeConflict(configs, 'current', domainScope, selectedDomainIds, verifiedDomainIds)).toBe(
            expected
        )
    })

    it.each([
        [
            'an incomplete SAML configuration',
            undefined,
            ConfigScopeEnumApi.Saml,
            'not_configured',
            [],
            { text: 'Add your identity provider details to enable SAML single sign-on.' },
        ],
        [
            'a partial SAML configuration',
            makeConfig({ saml_entity_id: 'entity-id' }),
            ConfigScopeEnumApi.Saml,
            'partially_configured',
            [],
            {
                text: 'Add ',
                emphasizedText: 'SAML ACS URL and SAML X.509 certificate',
                trailingText: ' to finish the configuration.',
            },
        ],
        [
            'an all-domain configuration',
            makeConfig({ domain_scope: DomainScopeEnumApi.All }),
            ConfigScopeEnumApi.Scim,
            'configured',
            [
                { id: 'first', domain: 'example.com', is_verified: true },
                { id: 'second', domain: 'example.org', is_verified: true },
            ],
            {
                text: 'Enabled for all verified domains: ',
                emphasizedText: 'example.com and example.org',
                trailingText: '.',
            },
        ],
        [
            'a selected-domain configuration',
            makeConfig({ organization_domain_ids: ['second'] }),
            ConfigScopeEnumApi.Xaa,
            'configured',
            [
                { id: 'first', domain: 'example.com', is_verified: true },
                { id: 'second', domain: 'example.org', is_verified: true },
            ],
            { text: 'Enabled for ', emphasizedText: 'example.org', trailingText: '.' },
        ],
    ] as const)('describes %s', (_, config, configScope, status, domains, expectedDescription) => {
        expect(getIdentityProviderConfigStatusDescription(config, configScope, status, [...domains])).toEqual(
            expectedDescription
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
