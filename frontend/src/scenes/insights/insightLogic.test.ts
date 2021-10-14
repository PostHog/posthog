import { defaultAPIMocks, mockAPI } from 'lib/api.mock'
import { expectLogic, initKeaTestLogic } from '~/test/kea-test-utils'
import { insightLogic } from './insightLogic'
import { AvailableFeature, PropertyOperator, ViewType } from '~/types'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

jest.mock('lib/api')

describe('insightLogic', () => {
    let logic: ReturnType<typeof insightLogic.build>

    mockAPI(async (url) => {
        const { pathname } = url
        if (['api/insight/42'].includes(pathname)) {
            return {
                result: ['result from api'],
                id: 42,
                filters: {
                    insight: ViewType.TRENDS,
                    events: [{ id: 3 }],
                    properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: 'a' }],
                },
            }
        } else if (['api/insight', 'api/insight/session/', 'api/insight/trend/'].includes(pathname)) {
            return { result: ['result from api'] }
        }
        return defaultAPIMocks(url, { availableFeatures: [AvailableFeature.DASHBOARD_COLLABORATION] })
    })

    it('requires props', () => {
        expect(() => {
            insightLogic()
        }).toThrow('Must init with dashboardItemId, even if undefined')
    })

    describe('when there is no props id', () => {
        initKeaTestLogic({
            logic: insightLogic,
            props: {
                dashboardItemId: undefined,
            },
            onLogic: (l) => (logic = l),
        })

        it('has the key set to "new"', () => {
            expect(logic.key).toEqual('new')
        })
    })

    describe('analytics', () => {
        initKeaTestLogic({
            logic: insightLogic,
            props: { dashboardItemId: undefined, filters: { insight: 'TRENDS' } },
            onLogic: (l) => (logic = l),
        })

        it('reports insight changes on setFilter', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ insight: 'FUNNELS' })
            }).toDispatchActions([
                eventUsageLogic.actionCreators.reportInsightViewed({ insight: 'FUNNELS' }, true, false, 0, {
                    changed_insight: 'TRENDS',
                }),
            ])
        })
    })

    describe('as dashboard item', () => {
        describe('props with filters and cached results', () => {
            initKeaTestLogic({
                logic: insightLogic,
                props: {
                    dashboardItemId: 42,
                    cachedResults: ['cached result'],
                    filters: {
                        insight: ViewType.TRENDS,
                        events: [{ id: 2 }],
                        properties: [{ value: 'lol', operator: PropertyOperator.Exact, key: 'lol', type: 'lol' }],
                    },
                },
                onLogic: (l) => (logic = l),
            })

            it('has the key set to the id', () => {
                expect(logic.key).toEqual(42)
            })
            it('no query to load results', async () => {
                await expectLogic(logic)
                    .toMatchValues({
                        insight: expect.objectContaining({ id: 42, result: ['cached result'] }),
                        filters: expect.objectContaining({
                            events: [{ id: 2 }],
                            properties: [expect.objectContaining({ type: 'lol' })],
                        }),
                    })
                    .toNotHaveDispatchedActions(['loadResultsSuccess']) // this took the cached results
            })
        })

        describe('props with filters, no cached results', () => {
            initKeaTestLogic({
                logic: insightLogic,
                props: {
                    dashboardItemId: 42,
                    cachedResults: undefined,
                    filters: {
                        insight: ViewType.TRENDS,
                        events: [{ id: 3 }],
                        properties: [{ value: 'a', operator: PropertyOperator.Exact, key: 'a', type: 'a' }],
                    },
                },
                onLogic: (l) => (logic = l),
            })

            it('makes a query to load the results', async () => {
                await expectLogic(logic)
                    .toDispatchActions(['loadResultsSuccess'])
                    .toMatchValues({
                        insight: expect.objectContaining({ id: 42, result: ['result from api'] }),
                        filters: expect.objectContaining({
                            events: [{ id: 3 }],
                            properties: [expect.objectContaining({ value: 'a' })],
                        }),
                    })
                    .toDispatchActions(['updateInsight', 'updateInsightSuccess'])
            })
        })

        describe('props with no filters, no cached results', () => {
            initKeaTestLogic({
                logic: insightLogic,
                props: {
                    dashboardItemId: 42,
                    cachedResults: undefined,
                    filters: undefined,
                },
                onLogic: (l) => (logic = l),
            })

            it('makes a query to load the results', async () => {
                await expectLogic(logic)
                    .toDispatchActions(['loadInsight', 'loadInsightSuccess'])
                    .printActions({ compact: true })
                    .toMatchValues({
                        insight: expect.objectContaining({ id: 42, result: ['result from api'] }),
                        filters: expect.objectContaining({
                            events: [{ id: 3 }],
                            properties: [expect.objectContaining({ value: 'a' })],
                        }),
                    })
            })
        })
    })
})
