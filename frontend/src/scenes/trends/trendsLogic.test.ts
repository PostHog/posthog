import { BuiltLogic } from 'kea'
import { defaultAPIMocks, mockAPI, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { trendsLogicType } from 'scenes/trends/trendsLogicType'
import { TrendResult } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

jest.mock('lib/api')

describe('trendsLogic', () => {
    let logic: BuiltLogic<trendsLogicType>

    mockAPI(async (url) => {
        const { pathname } = url
        if (pathname === `api/projects/${MOCK_TEAM_ID}/insights`) {
            return { results: [] }
        } else if (
            [
                `api/projects/${MOCK_TEAM_ID}/insights/123`,
                `api/projects/${MOCK_TEAM_ID}/insights/session/`,
                `api/projects/${MOCK_TEAM_ID}/insights/trend/`,
            ].includes(pathname)
        ) {
            return { result: ['result from api'] }
        }
        return defaultAPIMocks(url)
    })

    describe('core assumptions', () => {
        initKeaTestLogic({
            logic: trendsLogic,
            props: { dashboardItemId: undefined },
            onLogic: (l) => (logic = l),
        })

        it('loads results on mount', async () => {
            await expectLogic(logic).toDispatchActions([
                insightLogic({ dashboardItemId: undefined }).actionTypes.loadResults,
            ])
        })
    })

    describe('reducers', () => {
        initKeaTestLogic({
            logic: trendsLogic,
            props: { dashboardItemId: undefined },
            onLogic: (l) => (logic = l),
        })

        it('visibilityMap', async () => {
            const r = {} as TrendResult

            expectLogic(logic, () => {
                logic.actions.setVisibilityById({ '0': true, '2': false })
                logic.actions.setVisibilityById({ '8': true, '2': true })
            }).toMatchValues({ visibilityMap: { 0: true, 2: true, 8: true } })

            expectLogic(logic, () => {
                logic.actions.loadResultsSuccess({ result: [r, r], filters: {} })
            }).toMatchValues({ visibilityMap: { 0: true, 1: true } })

            expectLogic(logic, () => {
                logic.actions.toggleVisibility(1)
            }).toMatchValues({ visibilityMap: { 0: true, 1: false } })

            expectLogic(logic, () => {
                logic.actions.toggleVisibility(1)
            }).toMatchValues({ visibilityMap: { 0: true, 1: true } })
        })
    })

    describe('syncs with insightLogic', () => {
        const props = { dashboardItemId: 123 }
        initKeaTestLogic({
            logic: trendsLogic,
            props,
            onLogic: (l) => (logic = l),
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
