import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { QueryBasedInsightModel } from '~/types'

import { addSavedInsightsModalLogic } from './addSavedInsightsModalLogic'
import { insightDashboardModalLogic } from './insightDashboardModalLogic'

const createInsight = (id: number, name = 'test'): QueryBasedInsightModel =>
    ({
        id,
        name: `${name} ${id}`,
        short_id: `ii${id}`,
        order: 0,
        layouts: [],
        last_refresh: 'now',
        refreshing: false,
        created_by: null,
        is_sample: false,
        updated_at: 'now',
        result: {},
        color: null,
        created_at: 'now',
        dashboard: null,
        deleted: false,
        saved: true,
        query: {},
    }) as any as QueryBasedInsightModel

describe('insightDashboardModalLogic', () => {
    let logic: ReturnType<typeof insightDashboardModalLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': () => {
                    return [200, { count: 0, results: [] }]
                },
            },
        })
        initKeaTests()
        logic = insightDashboardModalLogic()
        logic.mount()
    })

    describe('optimistic dashboard state', () => {
        it('setOptimisticDashboardState updates state for an insight', async () => {
            await expectLogic(logic, () => {
                logic.actions.setOptimisticDashboardState(123, true)
            }).toMatchValues({
                optimisticDashboardState: { 123: true },
            })

            await expectLogic(logic, () => {
                logic.actions.setOptimisticDashboardState(456, false)
            }).toMatchValues({
                optimisticDashboardState: { 123: true, 456: false },
            })
        })

        it('clearOptimisticDashboardState removes state for an insight', async () => {
            logic.actions.setOptimisticDashboardState(123, true)
            logic.actions.setOptimisticDashboardState(456, false)

            await expectLogic(logic, () => {
                logic.actions.clearOptimisticDashboardState(123)
            }).toMatchValues({
                optimisticDashboardState: { 456: false },
            })
        })

        it('syncOptimisticStateWithDashboard clears state when it matches actual dashboard', async () => {
            logic.actions.setOptimisticDashboardState(1, true)
            logic.actions.setOptimisticDashboardState(2, false)

            // Insight 1 is in dashboard (matches optimistic true), should be cleared
            // Insight 2 is not in dashboard (matches optimistic false), should be cleared
            const tiles = [{ insight: { id: 1 } }]

            await expectLogic(logic, () => {
                logic.actions.syncOptimisticStateWithDashboard(tiles)
            }).toMatchValues({
                optimisticDashboardState: {},
            })
        })

        it('syncOptimisticStateWithDashboard keeps state when it differs from actual dashboard', async () => {
            logic.actions.setOptimisticDashboardState(1, false)
            logic.actions.setOptimisticDashboardState(2, true)

            // Insight 1 is in dashboard but optimistic says false - keep it
            // Insight 2 is not in dashboard but optimistic says true - keep it
            const tiles = [{ insight: { id: 1 } }]

            await expectLogic(logic, () => {
                logic.actions.syncOptimisticStateWithDashboard(tiles)
            }).toMatchValues({
                optimisticDashboardState: { 1: false, 2: true },
            })
        })

        it('isInsightInDashboard returns optimistic state when present', async () => {
            logic.actions.setOptimisticDashboardState(1, true)
            logic.actions.setOptimisticDashboardState(2, false)

            const insight1 = createInsight(1)
            const insight2 = createInsight(2)
            const insight3 = createInsight(3)

            const isInDashboard = logic.values.isInsightInDashboard
            const tiles = [{ insight: { id: 3 } }] // insight 3 is in the dashboard

            expect(isInDashboard(insight1, tiles)).toBe(true) // optimistic true
            expect(isInDashboard(insight2, tiles)).toBe(false) // optimistic false
            expect(isInDashboard(insight3, tiles)).toBe(true) // from dashboard tiles
            expect(isInDashboard(createInsight(4), tiles)).toBe(false) // not in either
        })

        it('dashboardUpdateFailed rolls back optimistic state', async () => {
            logic.actions.setOptimisticDashboardState(123, true)
            logic.actions.setOptimisticDashboardState(456, false)

            const parentLogic = addSavedInsightsModalLogic()
            parentLogic.mount()

            await expectLogic(logic, () => {
                parentLogic.actions.dashboardUpdateFailed(123)
            }).toMatchValues({
                optimisticDashboardState: { 456: false },
            })

            parentLogic.unmount()
        })
    })
})
