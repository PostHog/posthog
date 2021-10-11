import { BuiltLogic } from 'kea'
import { defaultAPIMocks, mockAPI } from 'lib/api.mock'
import { expectLogic, initKeaTestLogic } from '~/test/kea-test-utils'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { trendsLogicType } from 'scenes/trends/trendsLogicType'
import { TrendResult } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'

jest.mock('lib/api')

describe('trendsLogic', () => {
    let logic: BuiltLogic<trendsLogicType>

    mockAPI(async (url) => {
        const { pathname } = url
        if (['api/insight'].includes(pathname)) {
            return { results: [] }
        } else if (['api/insight/123', 'api/insight/session/', 'api/insight/trend/'].includes(pathname)) {
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
