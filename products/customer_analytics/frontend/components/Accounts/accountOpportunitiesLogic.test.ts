import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { insightsApi } from 'scenes/insights/utils/api'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightModel } from '~/types'

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

const ACCOUNT_VARIABLE = { variableId: 'var-1', code_name: 'salesforce_account_id', value: '' }

const buildInsight = (sql: string, variables: Record<string, typeof ACCOUNT_VARIABLE>): InsightModel =>
    ({
        short_id: 'xauPgpXt',
        query: {
            kind: NodeKind.DataVisualizationNode,
            source: { kind: NodeKind.HogQLQuery, query: sql, variables },
        },
    }) as unknown as InsightModel

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

    it('shows the not-linked state and loads no insight when the account has no Salesforce id', async () => {
        mockAccountsRetrieve.mockResolvedValue(buildAccount({}))
        const insightMock = jest.spyOn(insightsApi, 'getByShortId')

        await mount()

        expect(logic.values.opportunitiesResult).toEqual({ sfdcId: null, insight: null })
        expect(insightMock).not.toHaveBeenCalled()
    })

    it('surfaces a load-failed result (not an infinite skeleton) when the account fetch throws', async () => {
        mockAccountsRetrieve.mockRejectedValue(new Error('network'))
        const insightMock = jest.spyOn(insightsApi, 'getByShortId')

        await mount()

        expect(logic.values.opportunitiesResult).toEqual({ sfdcId: null, insight: null, loadFailed: true })
        expect(insightMock).not.toHaveBeenCalled()
    })

    it.each([
        ['is absent', () => jest.spyOn(insightsApi, 'getByShortId').mockResolvedValue(null)],
        ['fails to load', () => jest.spyOn(insightsApi, 'getByShortId').mockRejectedValue(new Error('boom'))],
    ])('shows the not-found state when the saved insight %s', async (_label, mockInsight) => {
        mockAccountsRetrieve.mockResolvedValue(buildAccount({ sfdc_id: 'sfdc-1' }))
        mockInsight()

        await mount()

        expect(logic.values.opportunitiesResult).toEqual({ sfdcId: 'sfdc-1', insight: null })
        expect(logic.values.variablesOverride).toBeNull()
    })

    it.each([
        [
            'sets the account Salesforce id on the variable',
            buildInsight('select 1 from salesforce.opportunity where account_id = {variables.salesforce_account_id}', {
                'var-1': ACCOUNT_VARIABLE,
            }),
            { 'var-1': { ...ACCOUNT_VARIABLE, value: 'sfdc-1' } },
        ],
        [
            'refuses an insight whose SQL does not filter by the variable',
            buildInsight('select 1 from salesforce.opportunity', { 'var-1': ACCOUNT_VARIABLE }),
            null,
        ],
        [
            'refuses an insight without the variable',
            buildInsight(
                'select 1 from salesforce.opportunity where account_id = {variables.salesforce_account_id}',
                {}
            ),
            null,
        ],
    ])('%s', async (_label, insight, expectedOverride) => {
        mockAccountsRetrieve.mockResolvedValue(buildAccount({ sfdc_id: 'sfdc-1' }))
        jest.spyOn(insightsApi, 'getByShortId').mockResolvedValue(insight)

        await mount()

        expect(logic.values.variablesOverride).toEqual(expectedOverride)
    })
})
