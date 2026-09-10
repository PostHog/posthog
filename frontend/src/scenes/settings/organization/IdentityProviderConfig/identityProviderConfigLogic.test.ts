import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import {
    ConfigScopeEnumApi,
    DomainScopeEnumApi,
    IdentityProviderConfigApi,
    OrganizationDomainApi,
} from '~/generated/core/api.schemas'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { identityProviderConfigLogic } from './identityProviderConfigLogic'

const makeDomain = (id: string): OrganizationDomainApi => ({
    id,
    domain: `${id}.example.com`,
    is_verified: true,
    verified_at: '2026-08-01T00:00:00Z',
    verification_challenge: 'challenge',
    scim_base_url: null,
})

const CREATED_CONFIG: IdentityProviderConfigApi = {
    id: '0198aaaa-0000-4000-8000-000000000001',
    domain_scope: DomainScopeEnumApi.All,
    config_scope: ConfigScopeEnumApi.Saml,
    organization_domain_ids: [],
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    has_saml: true,
    saml_relay_state: '0198bbbb-0000-4000-8000-000000000001',
    saml_entity_id: 'entity-id',
    saml_acs_url: 'https://idp.example.com/sso',
    saml_x509_cert: 'certificate',
    has_scim: false,
    scim_base_url: 'https://example.com/scim/v2/config',
    scim_bearer_token: null,
    has_id_jag: false,
}

describe('identityProviderConfigLogic', () => {
    it('loads every page of organization domains', async () => {
        const requestedOffsets: string[] = []
        const firstPageDomains = Array.from({ length: 100 }, (_, index) => makeDomain(`domain-${index}`))
        const secondPageDomain = makeDomain('domain-100')
        useMocks({
            get: {
                '/api/organizations/:organization/domains': ({ request }) => {
                    const offset = new URL(request.url).searchParams.get('offset') ?? '0'
                    requestedOffsets.push(offset)

                    return offset === '0'
                        ? [
                              200,
                              {
                                  count: 101,
                                  next: 'https://example.com/domains/?limit=100&offset=100',
                                  previous: null,
                                  results: firstPageDomains,
                              },
                          ]
                        : [
                              200,
                              {
                                  count: 101,
                                  next: null,
                                  previous: 'https://example.com/domains/?limit=100',
                                  results: [secondPageDomain],
                              },
                          ]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SSO_SETTINGS_REDESIGN], {
            [FEATURE_FLAGS.SSO_SETTINGS_REDESIGN]: true,
        })
        const logic = identityProviderConfigLogic({ configScope: ConfigScopeEnumApi.Saml, configId: 'new' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.organizationDomains).toHaveLength(101)
        expect(logic.values.organizationDomains?.[100]).toEqual(secondPageDomain)
        expect(logic.values.hasSamlDomainScopeConflict).toBe(false)
        expect(requestedOffsets).toEqual(['0', '100'])

        logic.unmount()
    })

    it('creates a new feature-scoped config that applies to all domains by default', async () => {
        let requestBody: Record<string, unknown> | null = null
        useMocks({
            get: {
                '/api/organizations/:organization/domains': { count: 0, next: null, previous: null, results: [] },
            },
            post: {
                '/api/organizations/:organization/identity_provider_configs': async ({ request }) => {
                    requestBody = (await request.json()) as Record<string, unknown>
                    return [201, CREATED_CONFIG]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SSO_SETTINGS_REDESIGN], {
            [FEATURE_FLAGS.SSO_SETTINGS_REDESIGN]: true,
        })
        const logic = identityProviderConfigLogic({ configScope: ConfigScopeEnumApi.Saml, configId: 'new' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.identityProviderConfigForm.domain_scope).toBe(DomainScopeEnumApi.All)
        expect(logic.values.identityProviderConfigFormChanged).toBe(false)

        const failureSpy = jest.spyOn(logic.actions, 'submitIdentityProviderConfigFormFailure')
        logic.actions.setIdentityProviderConfigFormValues({
            saml_entity_id: 'entity-id',
            saml_acs_url: 'https://idp.example.com/sso',
            saml_x509_cert: 'certificate',
        })
        expect(logic.values.identityProviderConfigFormChanged).toBe(true)
        logic.actions.submitIdentityProviderConfigForm()
        await expectLogic(logic).toFinishAllListeners()

        expect(failureSpy).not.toHaveBeenCalled()
        expect(logic.values.identityProviderConfigFormChanged).toBe(false)
        expect(requestBody).toMatchObject({
            config_scope: ConfigScopeEnumApi.Saml,
            domain_scope: DomainScopeEnumApi.All,
            organization_domain_ids: [],
            saml_entity_id: 'entity-id',
            saml_acs_url: 'https://idp.example.com/sso',
            saml_x509_cert: 'certificate',
        })
        // Saving keeps the user on the configuration page (the URL adopts the saved config's id)
        // so the generated SCIM base URL and one-time token remain visible.
        expect(router.values.location.pathname).toContain(
            urls.identityProviderConfig(ConfigScopeEnumApi.Saml, CREATED_CONFIG.id)
        )
    })

    it('keeps a user-edited name when the config list loads after the form is interactive', async () => {
        useMocks({
            get: {
                '/api/organizations/:organization/domains': { count: 0, next: null, previous: null, results: [] },
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SSO_SETTINGS_REDESIGN], {
            [FEATURE_FLAGS.SSO_SETTINGS_REDESIGN]: true,
        })
        const logic = identityProviderConfigLogic({ configScope: ConfigScopeEnumApi.Scim, configId: 'new' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setIdentityProviderConfigFormValues({ name: 'Okta production' })
        logic.actions.loadIdentityProviderConfigsSuccess([CREATED_CONFIG])

        expect(logic.values.identityProviderConfigForm.name).toBe('Okta production')
        expect(logic.values.identityProviderConfigFormChanged).toBe(true)

        logic.unmount()
    })

    it('reconciles the default name from the loaded config list while the form is untouched', async () => {
        useMocks({
            get: {
                '/api/organizations/:organization/domains': { count: 0, next: null, previous: null, results: [] },
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SSO_SETTINGS_REDESIGN], {
            [FEATURE_FLAGS.SSO_SETTINGS_REDESIGN]: true,
        })
        const logic = identityProviderConfigLogic({ configScope: ConfigScopeEnumApi.Scim, configId: 'new' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        // The initial guess assumed no existing configs; the list arriving later corrects it.
        expect(logic.values.identityProviderConfigForm.name).toBe('Default SCIM configuration')
        logic.actions.loadIdentityProviderConfigsSuccess([{ ...CREATED_CONFIG, config_scope: ConfigScopeEnumApi.Scim }])

        expect(logic.values.identityProviderConfigForm.name).toBe('')
        expect(logic.values.identityProviderConfigFormChanged).toBe(false)

        logic.unmount()
    })

    it('clears a stale delete confirmation when the delete modal reopens', async () => {
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SSO_SETTINGS_REDESIGN], {
            [FEATURE_FLAGS.SSO_SETTINGS_REDESIGN]: true,
        })
        const logic = identityProviderConfigLogic({ configScope: ConfigScopeEnumApi.Saml, configId: 'new' })
        logic.mount()

        logic.actions.openDeleteModal()
        logic.actions.setDeleteConfirmation('Delete x')
        expect(logic.values.isDeleteModalOpen).toBe(true)

        logic.actions.closeDeleteModal()
        logic.actions.openDeleteModal()

        expect(logic.values.isDeleteModalOpen).toBe(true)
        expect(logic.values.deleteConfirmation).toBe('')

        logic.unmount()
    })
})
