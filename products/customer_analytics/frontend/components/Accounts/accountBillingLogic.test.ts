import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { insightsApi } from 'scenes/insights/utils/api'

import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { QueryBasedInsightModel } from '~/types'

import { AccountBillingKind, accountBillingLogic, BILLING_INSIGHT_SHORT_IDS } from './accountBillingLogic'

const ORG_VARIABLE_ID = 'var-org'
const START_VARIABLE_ID = 'var-start'
const END_VARIABLE_ID = 'var-end'

const buildBillingInsight = (shortId: string): QueryBasedInsightModel =>
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
            Promise.resolve(buildBillingInsight(shortId))
        )
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe.each<AccountBillingKind>(['usage', 'spend'])('kind: %s', (kind) => {
        const mountForKind = (): void => {
            logic = accountBillingLogic({ accountId: 'acc-1', externalId: 'org-uuid', kind })
            logic.mount()
        }

        it('loads every saved insight configured for the kind', async () => {
            mountForKind()

            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.savedInsights?.map((insight) => insight.short_id)).toEqual(
                BILLING_INSIGHT_SHORT_IDS[kind]
            )
        })

        it('injects the external id into each saved insight variables', async () => {
            mountForKind()

            await expectLogic(logic).toFinishAllListeners()
            for (const shortId of BILLING_INSIGHT_SHORT_IDS[kind]) {
                expect(logic.values.variableOverridesByShortId[shortId]?.[ORG_VARIABLE_ID]?.value).toBe('org-uuid')
            }
        })

        it('updates the date variable overrides when the date range changes', async () => {
            mountForKind()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setDateRange('2024-01-01', '2024-01-31')

            const [firstShortId] = BILLING_INSIGHT_SHORT_IDS[kind]
            expect(logic.values.variableOverridesByShortId[firstShortId]?.[START_VARIABLE_ID]?.value).toBe('2024-01-01')
            expect(logic.values.variableOverridesByShortId[firstShortId]?.[END_VARIABLE_ID]?.value).toBe('2024-01-31')
        })

        it('changes the query key when the date range changes so the insight refetches', async () => {
            mountForKind()
            await expectLogic(logic).toFinishAllListeners()

            const [firstShortId] = BILLING_INSIGHT_SHORT_IDS[kind]
            const initialQueryKey = logic.values.queryKeyFor(firstShortId)

            logic.actions.setDateRange('2024-01-01', '2024-01-31')

            const nextQueryKey = logic.values.queryKeyFor(firstShortId)
            expect(nextQueryKey).not.toEqual(initialQueryKey)
            expect(nextQueryKey).toContain('2024-01-01')
            expect(nextQueryKey).toContain('2024-01-31')
        })

        // Guards the per-view invariant: hidden series are keyed per insight (the spend tab renders
        // two insights off one logic — hiding a series on one must not hide it on the other) and
        // reset when the date range changes (stale keys would otherwise hide series on the redrawn chart).
        it('toggles hidden series keys per insight and resets them on date change', () => {
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
            mountForKind()

            logic.actions.toggleHiddenSeriesKey('insight-a', 'Events-0', 3)
            logic.actions.toggleHiddenSeriesKey('insight-b', 'Recordings-1', 2)
            expect(logic.values.hiddenSeriesKeysByShortId).toEqual({
                'insight-a': ['Events-0'],
                'insight-b': ['Recordings-1'],
            })
            expect(captureSpy).toHaveBeenLastCalledWith('customer analytics account usage series toggled', {
                kind,
                is_hidden: true,
                series_count: 2,
            })

            logic.actions.toggleHiddenSeriesKey('insight-a', 'Events-0', 3)
            expect(logic.values.hiddenSeriesKeysByShortId).toEqual({ 'insight-a': [], 'insight-b': ['Recordings-1'] })
            expect(captureSpy).toHaveBeenLastCalledWith('customer analytics account usage series toggled', {
                kind,
                is_hidden: false,
                series_count: 3,
            })

            logic.actions.setDateRange('2024-01-01', '2024-01-31')
            expect(logic.values.hiddenSeriesKeysByShortId).toEqual({})
        })

        // Environments without the saved billing insight (or a failing fetch) must degrade to an
        // empty list, which is what drives the tab's not-found state instead of a crash or broken chart.
        it.each([
            ['is absent', () => jest.spyOn(insightsApi, 'getByShortId').mockResolvedValue(null)],
            ['fails to load', () => jest.spyOn(insightsApi, 'getByShortId').mockRejectedValue(new Error('boom'))],
        ])('resolves to no saved insights when the billing insight %s', async (_label, mockGetByShortId) => {
            mockGetByShortId()
            mountForKind()

            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.savedInsights).toEqual([])
        })
    })
})
