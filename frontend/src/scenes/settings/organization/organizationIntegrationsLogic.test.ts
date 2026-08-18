import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { organizationIntegrationsLogic } from './organizationIntegrationsLogic'

describe('organizationIntegrationsLogic', () => {
    let logic: ReturnType<typeof organizationIntegrationsLogic.build>

    beforeEach(() => {
        useMocks({ get: { '/api/organizations/:organization_id/integrations/': () => [503, { detail: 'boom' }] } })
        initKeaTests()
        logic = organizationIntegrationsLogic()
        logic.mount()
    })

    it('flags an error when the load fails, so the component can offer a retry', async () => {
        await expectLogic(logic).toDispatchActions(['loadOrganizationIntegrationsFailure']).toMatchValues({
            organizationIntegrationsError: true,
        })
    })

    it('clears the error once a retry succeeds', async () => {
        await expectLogic(logic).toDispatchActions(['loadOrganizationIntegrationsFailure'])

        useMocks({ get: { '/api/organizations/:organization_id/integrations/': { results: [] } } })
        logic.actions.loadOrganizationIntegrations()
        await expectLogic(logic).toDispatchActions(['loadOrganizationIntegrationsSuccess']).toMatchValues({
            organizationIntegrationsError: false,
        })
    })
})
