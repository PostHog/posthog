import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { googleAdsIntegrationLogic } from './googleAdsIntegrationLogic'

describe('googleAdsIntegrationLogic — accessible accounts error handling', () => {
    let logic: ReturnType<typeof googleAdsIntegrationLogic.build>
    let accountsResponse: [number, any]

    beforeEach(() => {
        accountsResponse = [200, { accessibleAccounts: [{ id: '1', name: 'Acme', level: '0', parent_id: '1' }] }]
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/:id/google_accessible_accounts': () => accountsResponse,
            },
        })
        initKeaTests()
        logic = googleAdsIntegrationLogic({ id: 1 })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('stores the error message instead of letting the rejection propagate', async () => {
        accountsResponse = [500, { type: 'server_error', detail: 'There was an internal error' }]
        await expectLogic(logic, () => {
            logic.actions.loadGoogleAdsAccessibleAccounts()
        }).toFinishAllListeners()

        expect(logic.values.googleAdsAccessibleAccounts).toBeNull()
        expect(logic.values.googleAdsAccessibleAccountsError).toBe('There was an internal error')
    })

    it('clears the error once a retry succeeds', async () => {
        accountsResponse = [500, { type: 'server_error', detail: 'There was an internal error' }]
        await expectLogic(logic, () => {
            logic.actions.loadGoogleAdsAccessibleAccounts()
        }).toFinishAllListeners()
        expect(logic.values.googleAdsAccessibleAccountsError).toBe('There was an internal error')

        accountsResponse = [200, { accessibleAccounts: [{ id: '1', name: 'Acme', level: '0', parent_id: '1' }] }]
        await expectLogic(logic, () => {
            logic.actions.loadGoogleAdsAccessibleAccounts()
        }).toFinishAllListeners()

        expect(logic.values.googleAdsAccessibleAccountsError).toBeNull()
        expect(logic.values.googleAdsAccessibleAccounts).toHaveLength(1)
    })
})
