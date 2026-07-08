import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { accountsRetrieve } from 'products/customer_analytics/frontend/generated/api'
import type { AccountApi, AccountApiProperties } from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountOpportunitiesLogic } from './accountOpportunitiesLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    // Keep the real module for everything else — connected logics (e.g. column config's
    // customPropertyDefinitionsList) call other generated functions on mount, and an
    // absent export makes their loaders throw on every test.
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountsRetrieve: jest.fn(),
}))

const mockAccountsRetrieve = accountsRetrieve as jest.MockedFunction<typeof accountsRetrieve>

const buildAccount = (properties: AccountApiProperties): AccountApi =>
    ({ id: 'acc-1', name: 'Acme', external_id: 'ext-1', properties }) as AccountApi

describe('accountOpportunitiesLogic', () => {
    let logic: ReturnType<typeof accountOpportunitiesLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
        jest.spyOn(posthog, 'captureException').mockReturnValue(undefined as any)
    })

    afterEach(() => {
        logic?.unmount()
    })

    const mount = async (): Promise<void> => {
        logic = accountOpportunitiesLogic({ accountId: 'acc-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    it('shows the not-linked state and runs no warehouse query when the account has no Salesforce id', async () => {
        mockAccountsRetrieve.mockResolvedValue(buildAccount({}))
        const queryMock = jest.spyOn(api, 'query')

        await mount()

        expect(logic.values.opportunitiesResult).toEqual({ sfdcId: null, opportunities: null })
        expect(queryMock).not.toHaveBeenCalled()
    })

    it('surfaces a load-failed result (not an infinite skeleton) when the account fetch throws', async () => {
        mockAccountsRetrieve.mockRejectedValue(new Error('network'))
        const queryMock = jest.spyOn(api, 'query')

        await mount()

        expect(logic.values.opportunitiesResult).toEqual({ sfdcId: null, opportunities: null, loadFailed: true })
        expect(queryMock).not.toHaveBeenCalled()
    })

    it.each([
        ['access is denied', "You don't have access to table `salesforce.opportunity`."],
        ['the table is absent', 'Unknown table `salesforce.opportunity`.'],
    ])('degrades to a null result without capturing the expected error when %s', async (_label, message) => {
        mockAccountsRetrieve.mockResolvedValue(buildAccount({ sfdc_id: 'sfdc-1' }))
        jest.spyOn(api, 'query').mockRejectedValue(new Error(message))

        await mount()

        expect(logic.values.opportunitiesResult).toEqual({ sfdcId: 'sfdc-1', opportunities: null })
        expect(posthog.captureException).not.toHaveBeenCalled()
    })

    it('still captures genuine, unexpected warehouse query failures', async () => {
        mockAccountsRetrieve.mockResolvedValue(buildAccount({ sfdc_id: 'sfdc-1' }))
        jest.spyOn(api, 'query').mockRejectedValue(new Error('Query exceeded memory limit'))

        await mount()

        expect(logic.values.opportunitiesResult).toEqual({ sfdcId: 'sfdc-1', opportunities: null })
        expect(posthog.captureException).toHaveBeenCalledTimes(1)
    })

    it('maps warehouse rows to opportunities preserving column order and nulls', async () => {
        mockAccountsRetrieve.mockResolvedValue(buildAccount({ sfdc_id: 'sfdc-1' }))
        jest.spyOn(api, 'query').mockResolvedValue({
            results: [
                ['op-1', 'Expansion', 50000, '2024-12-31', '2025-01-15'],
                ['op-2', null, null, null, null],
            ],
        } as any)

        await mount()

        expect(logic.values.opportunitiesResult).toEqual({
            sfdcId: 'sfdc-1',
            opportunities: [
                {
                    id: 'op-1',
                    name: 'Expansion',
                    totalCreditAmount: 50000,
                    closeDate: '2024-12-31',
                    contractStartDate: '2025-01-15',
                },
                { id: 'op-2', name: null, totalCreditAmount: null, closeDate: null, contractStartDate: null },
            ],
        })
    })
})
