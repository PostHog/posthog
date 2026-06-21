import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { organizationIntegrationsLogic } from './organizationIntegrationsLogic'

const MOCK_INTEGRATIONS = [
    {
        id: 1,
        kind: 'slack',
        config: {},
        created_by: null,
        created_at: '2026-01-01T00:00:00Z',
        display_name: 'PostHog workspace',
    },
]

describe('organizationIntegrationsLogic', () => {
    let logic: ReturnType<typeof organizationIntegrationsLogic.build>

    it('loads integrations on mount', async () => {
        useMocks({
            get: {
                '/api/organizations/:organization_id/integrations/': {
                    count: MOCK_INTEGRATIONS.length,
                    next: null,
                    previous: null,
                    results: MOCK_INTEGRATIONS,
                },
            },
        })
        initKeaTests()
        logic = organizationIntegrationsLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions([
            'loadOrganizationIntegrations',
            'loadOrganizationIntegrationsSuccess',
        ])

        expect(logic.values.organizationIntegrations).toHaveLength(1)
        expect(logic.values.organizationIntegrations?.[0].kind).toEqual('slack')
    })

    it('resolves to an empty list when the user has no current organization (404)', async () => {
        useMocks({
            get: {
                '/api/organizations/:organization_id/integrations/': () => [
                    404,
                    { type: 'invalid_request', code: 'not_found', detail: 'Organization not found.' },
                ],
            },
        })
        initKeaTests()
        logic = organizationIntegrationsLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadOrganizationIntegrations', 'loadOrganizationIntegrationsSuccess'])
            .toMatchValues({
                organizationIntegrations: [],
                organizationIntegrationsLoading: false,
            })
    })
})
