import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { googleAdsIntegrationLogic } from './googleAdsIntegrationLogic'

type LoaderCase = {
    label: string
    path: string
    successBody: any
    valueSelector: (logic: ReturnType<typeof googleAdsIntegrationLogic.build>) => unknown
    errorSelector: (logic: ReturnType<typeof googleAdsIntegrationLogic.build>) => string | null
    trigger: (logic: ReturnType<typeof googleAdsIntegrationLogic.build>) => void
}

const ACCESSIBLE_ACCOUNTS_SUCCESS = { accessibleAccounts: [{ id: '1', name: 'Acme', level: '0', parent_id: '1' }] }
const CONVERSION_ACTIONS_SUCCESS = { conversionActions: [{ id: 'A1', name: 'Purchase' }] }

const CASES: LoaderCase[] = [
    {
        label: 'accessible accounts',
        path: '/api/environments/:team_id/integrations/:id/google_accessible_accounts',
        successBody: ACCESSIBLE_ACCOUNTS_SUCCESS,
        valueSelector: (logic) => logic.values.googleAdsAccessibleAccounts,
        errorSelector: (logic) => logic.values.googleAdsAccessibleAccountsError,
        trigger: (logic) => logic.actions.loadGoogleAdsAccessibleAccounts(),
    },
    {
        label: 'conversion actions',
        path: '/api/environments/:team_id/integrations/:id/google_conversion_actions',
        successBody: CONVERSION_ACTIONS_SUCCESS,
        valueSelector: (logic) => logic.values.googleAdsConversionActions,
        errorSelector: (logic) => logic.values.googleAdsConversionActionsError,
        trigger: (logic) => logic.actions.loadGoogleAdsConversionActions('123', '456'),
    },
]

describe('googleAdsIntegrationLogic — loader error handling', () => {
    let logic: ReturnType<typeof googleAdsIntegrationLogic.build>

    describe.each(CASES)('$label', ({ path, successBody, valueSelector, errorSelector, trigger }) => {
        let response: [number, any]

        beforeEach(() => {
            response = [200, successBody]
            useMocks({
                get: {
                    [path]: () => response,
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
            response = [500, { type: 'server_error', detail: 'There was an internal error' }]
            await expectLogic(logic, () => {
                trigger(logic)
            }).toFinishAllListeners()

            expect(valueSelector(logic)).toBeNull()
            expect(errorSelector(logic)).toBe('There was an internal error')
        })

        it('clears the error once a retry succeeds', async () => {
            response = [500, { type: 'server_error', detail: 'There was an internal error' }]
            await expectLogic(logic, () => {
                trigger(logic)
            }).toFinishAllListeners()
            expect(errorSelector(logic)).toBe('There was an internal error')

            response = [200, successBody]
            await expectLogic(logic, () => {
                trigger(logic)
            }).toFinishAllListeners()

            expect(errorSelector(logic)).toBeNull()
            expect(valueSelector(logic)).toHaveLength(1)
        })
    })
})
