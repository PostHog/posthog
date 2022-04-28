import { expectLogic, truth } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import _dashboardJson from './__mocks__/dashboard.json'
import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { InsightModel, DashboardType, AppContext } from '~/types'
import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { dayjs, now } from 'lib/dayjs'
import posthog from 'posthog-js'

const dashboardJson = _dashboardJson as any as DashboardType

describe('dashboardLogic', () => {
    let logic: ReturnType<typeof dashboardLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/dashboards/5/': dashboardJson,
                '/api/projects/:team/dashboards/6/': {
                    ...dashboardJson,
                    items: [
                        { ...dashboardJson.items[0], result: null, last_refresh: null },
                        { ...dashboardJson.items[1], result: null, last_refresh: null },
                        { ...dashboardJson.items[0], id: 666, short_id: '666', last_refresh: now() },
                        { ...dashboardJson.items[1], id: 999, short_id: '999', last_refresh: now() },
                    ],
                },
                '/api/projects/:team/dashboards/7/': () => [500, '💣'],
                '/api/projects/:team/dashboards/8/': {
                    ...dashboardJson,
                    items: [{ id: 1001, short_id: '1001' }],
                },
                '/api/projects/:team/dashboards/9/': {
                    ...dashboardJson,
                    items: [{ ...dashboardJson.items[1], id: 800, short_id: '800', last_refresh: now() }],
                },
                '/api/projects/:team/insights/1001/': () => [500, '💣'],
                '/api/projects/:team/insights/800/': () => [
                    200,
                    { ...dashboardJson.items[1], id: 800, short_id: '800', last_refresh: now() },
                ],
                '/api/projects/:team/insights/:id/': (req) => [
                    200,
                    dashboardJson.items.find(({ id }: any) => String(id) === req.params['id']),
                ],
            },
        })
        initKeaTests()
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
                await expectLogic(logic).toMount([dashboardsModel, insightsModel, eventUsageLogic])
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
                        allItems: dashboardJson,
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
                            dashboardJson.items.map(({ short_id }) => short_id),
                            true
                        ),
                    ])
                    .toMatchValues({
                        refreshStatus: {
                            [dashboardJson.items[0].short_id]: { loading: true },
                            [dashboardJson.items[1].short_id]: { loading: true },
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
                            a.payload.item.short_id === dashboardJson.items[1].short_id,
                        (a) =>
                            a.type === dashboardsModel.actionTypes.updateDashboardItem &&
                            a.payload.item.short_id === dashboardJson.items[0].short_id,
                        // no longer reloading
                        logic.actionCreators.setRefreshStatus(dashboardJson.items[0].short_id, false),
                        logic.actionCreators.setRefreshStatus(dashboardJson.items[1].short_id, false),
                    ])
                    .toMatchValues({
                        refreshStatus: {
                            [dashboardJson.items[0].short_id]: { refreshed: true },
                            [dashboardJson.items[1].short_id]: { refreshed: true },
                        },
                        refreshMetrics: {
                            completed: 2,
                            total: 2,
                        },
                    })
            })

            it('reloads selected items', async () => {
                await expectLogic(logic, () => {
                    logic.actions.refreshAllDashboardItems([dashboardJson.items[0] as any])
                })
                    .toFinishAllListeners()
                    .toDispatchActions([
                        'refreshAllDashboardItems',
                        logic.actionCreators.setRefreshStatuses([dashboardJson.items[0].short_id], true),
                    ])
                    .toMatchValues({
                        refreshStatus: {
                            [dashboardJson.items[0].short_id]: { loading: true },
                        },
                        refreshMetrics: {
                            completed: 0,
                            total: 1,
                        },
                    })
                    .toDispatchActionsInAnyOrder([
                        (a) =>
                            a.type === dashboardsModel.actionTypes.updateDashboardItem &&
                            a.payload.item.short_id === dashboardJson.items[0].short_id,
                        logic.actionCreators.setRefreshStatus(dashboardJson.items[0].short_id, false),
                    ])
                    .toMatchValues({
                        refreshStatus: {
                            [dashboardJson.items[0].short_id]: { refreshed: true },
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

        it('should refresh all dashboards if lastRefreshed is older than 3 hours and the feature flag is set', async () => {
            // Bit of a hack to set the 'auto-refresh-dashboards' feature flag
            window.POSTHOG_APP_CONTEXT = {
                ...window.POSTHOG_APP_CONTEXT,
                persisted_feature_flags: ['auto-refresh-dashboards'],
            } as unknown as AppContext
            posthog.reloadFeatureFlags()

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
