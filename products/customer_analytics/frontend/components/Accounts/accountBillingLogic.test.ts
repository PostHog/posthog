import { expectLogic } from 'kea-test-utils'

import { insightsApi } from 'scenes/insights/utils/api'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { QueryBasedInsightModel } from '~/types'

import { accountBillingLogic } from './accountBillingLogic'

const ORG_VARIABLE_ID = 'var-org'
const START_VARIABLE_ID = 'var-start'
const END_VARIABLE_ID = 'var-end'

const buildUsageInsight = (): QueryBasedInsightModel =>
    ({
        query: {
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'SELECT 1',
                variables: {
                    [ORG_VARIABLE_ID]: { variableId: ORG_VARIABLE_ID, code_name: 'billing_org_id', value: null },
                    [START_VARIABLE_ID]: {
                        variableId: START_VARIABLE_ID,
                        code_name: 'billing_start_date',
                        value: null,
                    },
                    [END_VARIABLE_ID]: { variableId: END_VARIABLE_ID, code_name: 'billing_end_date', value: null },
                },
            },
        },
    }) as unknown as QueryBasedInsightModel

describe('accountBillingLogic', () => {
    let logic: ReturnType<typeof accountBillingLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.restoreAllMocks()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('injects the external id into the saved insight variables', async () => {
        jest.spyOn(insightsApi, 'getByShortId').mockResolvedValue(buildUsageInsight())

        logic = accountBillingLogic({ accountId: 'acc-1', externalId: 'org-uuid', kind: 'usage' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.variableOverrides?.[ORG_VARIABLE_ID]?.value).toBe('org-uuid')
    })

    it('updates the date variable overrides when the date range changes', async () => {
        jest.spyOn(insightsApi, 'getByShortId').mockResolvedValue(buildUsageInsight())

        logic = accountBillingLogic({ accountId: 'acc-1', externalId: 'org-uuid', kind: 'usage' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setDateRange('2024-01-01', '2024-01-31')

        expect(logic.values.variableOverrides?.[START_VARIABLE_ID]?.value).toBe('2024-01-01')
        expect(logic.values.variableOverrides?.[END_VARIABLE_ID]?.value).toBe('2024-01-31')
    })

    it('changes the query key when the date range changes so the insight refetches', async () => {
        jest.spyOn(insightsApi, 'getByShortId').mockResolvedValue(buildUsageInsight())

        logic = accountBillingLogic({ accountId: 'acc-1', externalId: 'org-uuid', kind: 'usage' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        const initialQueryKey = logic.values.queryKey

        logic.actions.setDateRange('2024-01-01', '2024-01-31')

        expect(logic.values.queryKey).not.toEqual(initialQueryKey)
        expect(logic.values.queryKey).toContain('2024-01-01')
        expect(logic.values.queryKey).toContain('2024-01-31')
    })
})
