import { mockAPI } from 'lib/api.mock'
import { expectLogic, initKeaTestLogic } from '~/test/kea-test-utils'
import { insightLogic } from './insightLogic'
import { AvailableFeature, PropertyOperator, ViewType } from '~/types'

jest.mock('lib/api')

describe('insightLogic', () => {
    let logic: ReturnType<typeof insightLogic.build>

    mockAPI(async ({ pathname, searchParams }) => {
        if (pathname === '_preflight/') {
            return { is_clickhouse_enabled: true }
        } else if (['api/organizations/@current', 'api/projects/@current', 'api/dashboard'].includes(pathname)) {
            return { results: [] }
        } else if (pathname === 'api/users/@me/') {
            return {
                results: {
                    organization: {
                        available_features: [AvailableFeature.DASHBOARD_COLLABORATION],
                    },
                },
            }
        } else if (['api/insight/42'].includes(pathname)) {
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
        } else {
            throw new Error(`Unmocked fetch to: ${pathname} with params: ${JSON.stringify(searchParams)}`)
        }
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
