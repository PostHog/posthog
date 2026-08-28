import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { ConfigScopeEnumApi, DomainScopeEnumApi, IdentityProviderConfigApi } from '~/generated/core/api.schemas'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { identityProviderConfigLogic } from './identityProviderConfigLogic'

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
    })
})
