import { defaultAPIMocks, mockAPI, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { pathsLogic } from 'scenes/paths/pathsLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightShortId, InsightType } from '~/types'

jest.mock('lib/api')

const Insight123 = '123' as InsightShortId

describe('pathsLogic', () => {
    let logic: ReturnType<typeof pathsLogic.build>

    mockAPI(async (url) => {
        const { pathname } = url
        if (
            [
                `api/projects/${MOCK_TEAM_ID}/insights/path`,
                `api/projects/${MOCK_TEAM_ID}/insights/paths/`,
                `api/projects/${MOCK_TEAM_ID}/insights/123`,
                `api/projects/${MOCK_TEAM_ID}/insights`,
            ].includes(pathname)
        ) {
            return { result: ['result from api'] }
        }
        return defaultAPIMocks(url)
    })

    describe('syncs with insightLogic', () => {
        const props = { dashboardItemId: Insight123 }
        initKeaTestLogic({
            logic: pathsLogic,
            props,
            onLogic: (l) => (logic = l),
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
