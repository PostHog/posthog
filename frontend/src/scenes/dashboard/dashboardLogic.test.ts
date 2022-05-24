import { expectLogic, truth } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import _dashboardJson from './__mocks__/dashboard.json'
import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { InsightModel, DashboardType, InsightShortId } from '~/types'
import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { dayjs, now } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

const dashboardJson = _dashboardJson as any as DashboardType

function insightsOnDashboard(dashboardsRelation: number[]): InsightModel[] {
    return dashboardJson.items.map((i) => ({ ...i, dashboards: dashboardsRelation }))
}

const dashboardResult = (dashboardId: number, items: InsightModel[]): DashboardType => {
    return {
        ...dashboardJson,
        id: dashboardId,
        items: [...items],
    }
}

const uncached = (insight: InsightModel): InsightModel => ({ ...insight, result: null, last_refresh: null })

describe('dashboardLogic', () => {
    let logic: ReturnType<typeof dashboardLogic.build>

    /**
     * This test setup is tightly coupled to how the API behaves
     *  (instead of being a list of mock results based on order of calls)
     *  in order to clarify the behaviour of the interacting logics it tests
     *
     * starting state
     *
     * dashboards:  5, 6, 8, 9, 10
     * insights: 175, 172, 666, 800, 999, 1001
     *
     *                  d5             d8 - i1001
     *                /    \
     *             i172    i175
     *               \      /
     *                  d6              d9 - i800 - d10
     *               /     \
     *             i666    i999
     */
    let dashboards = {}

    beforeEach(() => {
        const insights: Record<number, InsightModel> = {
            172: { ...insightsOnDashboard([5, 6])[1], short_id: '172' as InsightShortId },
            175: { ...insightsOnDashboard([5, 6])[0], short_id: '175' as InsightShortId },
            666: {
                ...insightsOnDashboard([6])[0],
                id: 666,
                short_id: '666' as InsightShortId,
                last_refresh: now().toISOString(),
            },
            999: {
                ...insightsOnDashboard([6])[0],
                id: 999,
                short_id: '999' as InsightShortId,
                last_refresh: now().toISOString(),
            },
            1001: { id: 1001, short_id: '1001' as InsightShortId } as unknown as InsightModel,
            800: {
                ...insightsOnDashboard([9, 10])[1],
                id: 800,
                short_id: '800' as InsightShortId,
                last_refresh: now().toISOString(),
            },
        }
        dashboards = {
            5: { ...dashboardResult(5, [insights['172'], insights['175']]) },
            6: {
                ...dashboardResult(6, [
                    uncached(insights['172']),
                    uncached(insights['175']),
                    insights['666'],
                    insights['999'],
                ]),
            },
            8: {
                ...dashboardResult(8, [insights['1001']]),
            },
            9: {
                ...dashboardResult(9, [insights['800']]),
            },
            10: {
                ...dashboardResult(10, [insights['800']]),
            },
        }
        useMocks({
            get: {
                '/api/projects/:team/dashboards/5/': { ...dashboards['5'] },
                '/api/projects/:team/dashboards/6/': { ...dashboards['6'] },
                '/api/projects/:team/dashboards/7/': () => [500, '💣'],
                '/api/projects/:team/dashboards/8/': { ...dashboards['8'] },
                '/api/projects/:team/dashboards/9/': { ...dashboards['9'] },
                '/api/projects/:team/dashboards/10/': { ...dashboards['10'] },
                '/api/projects/:team/dashboards/': {
                    count: 6,
                    next: null,
                    previous: null,
                    results: [
                        { ...dashboards['5'] },
                        { ...dashboards['6'] },
                        { ...dashboards['8'] },
                        { ...dashboards['9'] },
                        { ...dashboards['10'] },
                    ],
                },
                '/api/projects/:team/insights/1001/': () => [500, '💣'],
                '/api/projects/:team/insights/800/': () => [200, { ...insights['800'] }],
                '/api/projects/:team/insights/:id/': (req) => {
                    const dashboard = req.url.searchParams.get('from_dashboard')
                    if (!dashboard) {
                        throw new Error('the logic must always add this param')
                    }
                    const matched = insights[req.params['id']]
                    if (matched) {
                        return [200, matched]
                    } else {
                        return [404, null]
                    }
                },
            },
            patch: {
                '/api/projects/:team/insights/:id/': (req) => {
                    try {
                        if (typeof req.body !== 'object') {
                            return [500, `this update should receive an object body not ${req.body}`]
                        }
                        const updates = req.body
                        const insightId = req.params.id

                        const starting = insights[insightId]
                        insights[insightId] = {
                            ...starting,
                            ...updates,
                        }

                        starting.dashboards?.forEach((dashboardId) => {
                            // remove this insight from any dashboard it is already on
                            dashboards[dashboardId].items = dashboards[dashboardId].items.filter(
                                (i: InsightModel) => i.id !== starting.id
                            )
                        })

                        insights[insightId].dashboards?.forEach((dashboardId) => {
                            // then add it to any it now references
                            dashboards[dashboardId].items.push(insights[insightId])
                        })

                        return [200, insights[insightId]]
                    } catch (e) {
                        return [500, e]
                    }
                },
            },
        })
        initKeaTests()
    })

    describe('moving between dashboards', () => {
        beforeEach(() => {
            logic = dashboardLogic({ id: 9 })
            logic.mount()
        })

        it('only replaces the source dashboard with the target', async () => {
            const startingDashboard = dashboards['9']
            const expectedDashboard = dashboardResult(9, [])

            const insights = startingDashboard.items
            const sourceInsight = insights[0]

            await expectLogic(logic, () => {
                insightsModel.actions.moveToDashboard(sourceInsight, 9, 8, 'targetDashboard')
            })
                .toFinishAllListeners()
                .toMatchValues({
                    allItems: expectedDashboard,
                })
        })
    })

    describe('when there is no props id', () => {
        beforeEach(() => {
            logic = dashboardLogic({ id: undefined })
            logic.mount()
        })

        it('does not fetch dashboard items on mount', async () => {
            await expectLogic(logic).toNotHaveDispatchedActions(['loadDashboardItems'])
        })
    })

    describe('when the dashboard API errors', () => {
        beforeEach(silenceKeaLoadersErrors)
        afterEach(resumeKeaLoadersErrors)

        beforeEach(() => {
            logic = dashboardLogic({ id: 7 })
            logic.mount()
        })

        it('allows consumers to respond', async () => {
            await expectLogic(logic).toFinishAllListeners().toMatchValues({
                receivedErrorsFromAPI: true,
            })
        })
    })

    describe('when a dashboard item API errors', () => {
        beforeEach(() => {
            logic = dashboardLogic({ id: 8 })
            logic.mount()
        })

        it('allows consumers to respond', async () => {
            await expectLogic(logic, () => {
                // try and load dashboard items data once dashboard is loaded
                logic.actions.refreshAllDashboardItemsManual()
            })
                .toFinishAllListeners()
                .toMatchValues({
                    refreshStatus: { 1001: { error: true } },
                })
        })
    })

    describe('when props id is set to a number', () => {
        beforeEach(async () => {
            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
        })

        describe('on load', () => {
            it('mounts other logics', async () => {
                await expectLogic(logic).toMount([
                    dashboardsModel,
                    insightsModel,
                    eventUsageLogic,
                    teamLogic,
                    featureFlagLogic,
                ])
            })

            it('fetches dashboard items on mount', async () => {
                await expectLogic(logic)
                    .toDispatchActions(['loadDashboardItems'])
                    .toMatchValues({
                        allItems: null,
                        items: undefined,
                    })
                    .toDispatchActions(['loadDashboardItemsSuccess'])
                    .toMatchValues({
                        allItems: dashboards['5'],
                        items: truth((items) => items.length === 2),
                        receivedErrorsFromAPI: false,
                    })
            })
        })

        describe('reload items', () => {
            it('reloads all items', async () => {
                await expectLogic(logic, () => {
                    logic.actions.refreshAllDashboardItemsManual()
                })
                    .toDispatchActions([
                        // starts loading
                        'refreshAllDashboardItemsManual',
                        'refreshAllDashboardItems',
                        // sets the "reloading" status
                        logic.actionCreators.setRefreshStatuses(
                            dashboards['5'].items.map(({ short_id }: InsightModel) => short_id),
                            true
                        ),
                    ])
                    .toMatchValues({
                        refreshStatus: {
                            [dashboards['5'].items[0].short_id]: { loading: true },
                            [dashboards['5'].items[1].short_id]: { loading: true },
                        },
                        refreshMetrics: {
                            completed: 0,
                            total: 2,
                        },
                    })
                    .toDispatchActionsInAnyOrder([
                        // and updates the action in the model
                        (a) =>
                            a.type === dashboardsModel.actionTypes.updateDashboardItem &&
                            a.payload.item.short_id === dashboards['5'].items[1].short_id,
                        (a) =>
                            a.type === dashboardsModel.actionTypes.updateDashboardItem &&
                            a.payload.item.short_id === dashboards['5'].items[0].short_id,
                        // no longer reloading
                        logic.actionCreators.setRefreshStatus(dashboards['5'].items[0].short_id, false),
                        logic.actionCreators.setRefreshStatus(dashboards['5'].items[1].short_id, false),
                    ])
                    .toMatchValues({
                        refreshStatus: {
                            [dashboards['5'].items[0].short_id]: { refreshed: true },
                            [dashboards['5'].items[1].short_id]: { refreshed: true },
                        },
                        refreshMetrics: {
                            completed: 2,
                            total: 2,
                        },
                    })
            })

            it('reloads selected items', async () => {
                await expectLogic(logic, () => {
                    logic.actions.refreshAllDashboardItems([dashboards['5'].items[0] as any])
                })
                    .toFinishAllListeners()
                    .toDispatchActions([
                        'refreshAllDashboardItems',
                        logic.actionCreators.setRefreshStatuses([dashboards['5'].items[0].short_id], true),
                    ])
                    .toMatchValues({
                        refreshStatus: {
                            [dashboards['5'].items[0].short_id]: { loading: true },
                        },
                        refreshMetrics: {
                            completed: 0,
                            total: 1,
                        },
                    })
                    .toDispatchActionsInAnyOrder([
                        (a) =>
                            a.type === dashboardsModel.actionTypes.updateDashboardItem &&
                            a.payload.item.short_id === dashboards['5'].items[0].short_id,
                        logic.actionCreators.setRefreshStatus(dashboards['5'].items[0].short_id, false),
                    ])
                    .toMatchValues({
                        refreshStatus: {
                            [dashboards['5'].items[0].short_id]: { refreshed: true },
                        },
                        refreshMetrics: {
                            completed: 1,
                            total: 1,
                        },
                    })
            })
        })
    })

    describe('with a half-cached dashboard', () => {
        beforeEach(() => {
            logic = dashboardLogic({ id: 6 })
            logic.mount()
        })

        it('fetches dashboard items on mount', async () => {
            await expectLogic(logic)
                .toFinishAllListeners()
                .toDispatchActions(['loadDashboardItemsSuccess'])
                .toMatchValues({
                    allItems: truth(({ items }) => items.filter((i: InsightModel) => i.result === null).length === 2),
                    items: truth((items) => items.length === 4),
                })
                .toDispatchActions(['refreshAllDashboardItems', 'setRefreshStatuses'])
                .toMatchValues({
                    refreshMetrics: {
                        completed: 0,
                        total: 2,
                    },
                })
                .toDispatchActions(['setRefreshStatus', 'setRefreshStatus'])
                .toMatchValues({
                    refreshMetrics: {
                        completed: 2,
                        total: 2,
                    },
                })
                .toMatchValues({
                    allItems: truth(({ items }) => items.filter((i: InsightModel) => i.result === null).length === 0),
                    items: truth((items) => items.length === 4),
                })
        })
    })
    describe('lastRefreshed', () => {
        it('should be the earliest refreshed dashboard', async () => {
            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic)
                .toFinishAllListeners()
                .toMatchValues({
                    lastRefreshed: dayjs('2021-09-21T11:48:48.444504Z'),
                })
        })

        it('should refresh all dashboards if lastRefreshed is older than 3 hours', async () => {
            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['refreshAllDashboardItems']).toFinishAllListeners()
        })

        it('should not refresh all dashboards if lastRefreshed is older than 3 hours but the feature flag is not set', async () => {
            logic = dashboardLogic({ id: 5 })
            logic.mount()
            await expectLogic(logic).toNotHaveDispatchedActions(['refreshAllDashboardItems']).toFinishAllListeners()
        })

        it('should not refresh if lastRefreshed is less than 3 hours', async () => {
            logic = dashboardLogic({ id: 9 })
            logic.mount()
            await expectLogic(logic)
                .toDispatchActions(['loadDashboardItemsSuccess'])
                .toNotHaveDispatchedActions(['refreshAllDashboardItems'])
                .toFinishListeners()
        })
    })
})
