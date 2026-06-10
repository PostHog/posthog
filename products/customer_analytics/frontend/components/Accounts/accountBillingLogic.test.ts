import { expectLogic } from 'kea-test-utils'

import { insightsApi } from 'scenes/insights/utils/api'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { QueryBasedInsightModel } from '~/types'

import { accountBillingLogic, BILLING_INSIGHT_SHORT_IDS } from './accountBillingLogic'

const ORG_VARIABLE_ID = 'var-org'
const START_VARIABLE_ID = 'var-start'
const END_VARIABLE_ID = 'var-end'

const buildSpendInsight = (shortId: string): QueryBasedInsightModel =>
    ({
        short_id: shortId,
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
        jest.spyOn(insightsApi, 'getByShortId').mockImplementation((shortId) =>
            Promise.resolve(buildSpendInsight(shortId))
        )
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads every saved insight configured for the kind', async () => {
        logic = accountBillingLogic({ accountId: 'acc-1', externalId: 'org-uuid', kind: 'spend' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.savedInsights?.map((insight) => insight.short_id)).toEqual(BILLING_INSIGHT_SHORT_IDS.spend)
    })

    it('injects the external id into each saved insight variables', async () => {
        logic = accountBillingLogic({ accountId: 'acc-1', externalId: 'org-uuid', kind: 'spend' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        for (const shortId of BILLING_INSIGHT_SHORT_IDS.spend) {
            expect(logic.values.variableOverridesByShortId[shortId]?.[ORG_VARIABLE_ID]?.value).toBe('org-uuid')
        }
    })

    it('updates the date variable overrides when the date range changes', async () => {
        logic = accountBillingLogic({ accountId: 'acc-1', externalId: 'org-uuid', kind: 'spend' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setDateRange('2024-01-01', '2024-01-31')

        const [firstShortId] = BILLING_INSIGHT_SHORT_IDS.spend
        expect(logic.values.variableOverridesByShortId[firstShortId]?.[START_VARIABLE_ID]?.value).toBe('2024-01-01')
        expect(logic.values.variableOverridesByShortId[firstShortId]?.[END_VARIABLE_ID]?.value).toBe('2024-01-31')
    })

    it('changes the query key when the date range changes so the insight refetches', async () => {
        logic = accountBillingLogic({ accountId: 'acc-1', externalId: 'org-uuid', kind: 'spend' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        const [firstShortId] = BILLING_INSIGHT_SHORT_IDS.spend
        const initialQueryKey = logic.values.queryKeyFor(firstShortId)

        logic.actions.setDateRange('2024-01-01', '2024-01-31')

        const nextQueryKey = logic.values.queryKeyFor(firstShortId)
        expect(nextQueryKey).not.toEqual(initialQueryKey)
        expect(nextQueryKey).toContain('2024-01-01')
        expect(nextQueryKey).toContain('2024-01-31')
    })
})
