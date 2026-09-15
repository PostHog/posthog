import { expectLogic } from 'kea-test-utils'

import { ConfigScopeEnumApi, IdentityProviderConfigApi } from '~/generated/core/api.schemas'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { identityProviderConfigsLogic } from './identityProviderConfigsLogic'

const makeConfig = (id: string): IdentityProviderConfigApi => ({
    id,
    config_scope: ConfigScopeEnumApi.Saml,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    has_saml: true,
    saml_relay_state: 'relay-state',
    has_scim: false,
    scim_base_url: `https://example.com/scim/v2/${id}`,
    scim_bearer_token: null,
    has_id_jag: false,
})

describe('identityProviderConfigsLogic', () => {
    it('loads every page of identity provider configurations', async () => {
        const requestedOffsets: string[] = []
        const firstPageConfigs = Array.from({ length: 100 }, (_, index) => makeConfig(`config-${index}`))
        const secondPageConfig = makeConfig('config-100')
        useMocks({
            get: {
                '/api/organizations/:organization/identity_provider_configs': ({ request }) => {
                    const offset = new URL(request.url).searchParams.get('offset') ?? '0'
                    requestedOffsets.push(offset)

                    return offset === '0'
                        ? [
                              200,
                              {
                                  count: 101,
                                  next: 'https://example.com/identity_provider_configs/?limit=100&offset=100',
                                  previous: null,
                                  results: firstPageConfigs,
                              },
                          ]
                        : [
                              200,
                              {
                                  count: 101,
                                  next: null,
                                  previous: 'https://example.com/identity_provider_configs/?limit=100',
                                  results: [secondPageConfig],
                              },
                          ]
                },
            },
        })
        initKeaTests()
        const logic = identityProviderConfigsLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.identityProviderConfigs).toHaveLength(101)
        expect(logic.values.identityProviderConfigs?.[100]).toEqual(secondPageConfig)
        expect(requestedOffsets).toEqual(['0', '100'])

        logic.unmount()
    })
})
