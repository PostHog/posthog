import { expectLogic } from 'kea-test-utils'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { InsightShortId, InsightType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

const Insight123 = '123' as InsightShortId

describe('trendsLogic', () => {
    let logic: ReturnType<typeof trendsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/insights': { results: ['result from api'] },
                '/api/projects/:team/insights/123': { result: ['result from api'] },
                '/api/projects/:team/insights/trend/': { result: ['result from api'] },
            },
        })
        initKeaTests()
    })

    describe('core assumptions', () => {
        beforeEach(() => {
            logic = trendsLogic({
                dashboardItemId: undefined,
                cachedInsight: { filters: { insight: InsightType.TRENDS } },
            })
            logic.mount()
        })
        it('loads results on mount if with filters', async () => {
            await expectLogic(logic).toDispatchActions([
                insightLogic({ dashboardItemId: undefined }).actionTypes.loadResults,
            ])
        })
    })

    describe('syncs with insightLogic', () => {
        const props = { dashboardItemId: Insight123 }
        beforeEach(() => {
            logic = trendsLogic(props)
            logic.mount()
        })

        it('setFilters calls insightLogic.setFilters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ events: [{ id: 42 }] })
            })
                .toDispatchActions([
                    (action) =>
                        action.type === insightLogic(props).actionTypes.setFilters &&
                        action.payload.filters?.events?.[0]?.id === 42,
                ])
                .toMatchValues(logic, {
                    filters: expect.objectContaining({
                        events: [{ id: 42 }],
                    }),
                })
                .toMatchValues(insightLogic(props), {
                    filters: expect.objectContaining({
                        events: [{ id: 42 }],
                    }),
                })
        })

        it('insightLogic.setFilters updates filters', async () => {
            await expectLogic(logic, () => {
                insightLogic(props).actions.setFilters({ events: [{ id: 42 }] })
            })
                .toMatchValues(logic, {
                    filters: expect.objectContaining({
                        events: [{ id: 42 }],
                    }),
                })
                .toMatchValues(insightLogic(props), {
                    filters: expect.objectContaining({
                        events: [{ id: 42 }],
                    }),
                })
        })
    })
})
