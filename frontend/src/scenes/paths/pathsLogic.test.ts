import { expectLogic } from 'kea-test-utils'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightShortId, InsightType } from '~/types'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

jest.mock('lib/api')

const Insight123 = '123' as InsightShortId

describe('pathsLogic', () => {
    let logic: ReturnType<typeof pathsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/insights/paths/': { result: ['result from api'] },
                '/api/projects/:team/insights/trend/': { result: ['result from api'] },
                '/api/projects/:team/insights': { result: ['result from api'] },
            },
            post: {
                '/api/projects/:team/insights/path/': { result: ['result from api'] },
            },
        })
    })

    describe('syncs with insightLogic', () => {
        const props = { dashboardItemId: Insight123 }
        beforeEach(() => {
            initKeaTests()
            logic = pathsLogic(props)
            logic.mount()
        })

        it('setFilter calls insightLogic.setFilters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilter({
                    insight: InsightType.PATHS,
                    step_limit: 999,
                })
            })
                .toDispatchActions([
                    (action) =>
                        action.type === insightLogic(props).actionTypes.setFilters &&
                        action.payload.filters?.step_limit === 999,
                ])
                .toMatchValues(logic, {
                    filter: expect.objectContaining({
                        step_limit: 999,
                    }),
                })
                .toMatchValues(insightLogic(props), {
                    filters: expect.objectContaining({
                        step_limit: 999,
                    }),
                })
        })

        it('insightLogic.setFilters updates filter', async () => {
            await expectLogic(logic, () => {
                insightLogic(props).actions.setFilters({
                    insight: InsightType.PATHS,
                    step_limit: 999,
                })
            })
                .toMatchValues(logic, {
                    filter: expect.objectContaining({
                        step_limit: 999,
                    }),
                })
                .toMatchValues(insightLogic(props), {
                    filters: expect.objectContaining({
                        step_limit: 999,
                    }),
                })
        })

        it('insightLogic.setFilters updates edge limits', async () => {
            await expectLogic(logic, () => {
                insightLogic(props).actions.setFilters({
                    insight: InsightType.PATHS,
                    edge_limit: 60,
                    min_edge_weight: 5,
                    max_edge_weight: 10,
                })
            })
                .toMatchValues(logic, {
                    filter: expect.objectContaining({
                        edge_limit: 60,
                        min_edge_weight: 5,
                        max_edge_weight: 10,
                    }),
                })
                .toMatchValues(insightLogic(props), {
                    filters: expect.objectContaining({
                        edge_limit: 60,
                        min_edge_weight: 5,
                        max_edge_weight: 10,
                    }),
                })
        })
    })
})
