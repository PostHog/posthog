import { BuiltLogic } from 'kea'
import { defaultAPIMocks, mockAPI } from 'lib/api.mock'
import { expectLogic, truth } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import dashboardJson from './__mocks__/dashboard.json'
import { dashboardLogicType } from 'scenes/dashboard/dashboardLogicType'
import { dashboardsModel } from '~/models/dashboardsModel'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

jest.mock('lib/api')

describe('dashboardLogic', () => {
    let logic: BuiltLogic<dashboardLogicType>

    mockAPI(async (url) => {
        const { pathname } = url
        if (pathname === 'api/dashboard/5/') {
            return dashboardJson
        } else if (pathname.startsWith('api/dashboard_item/')) {
            return dashboardJson.items.find(({ id }) => id === parseInt(pathname.split('/')[2]))
        }
        return defaultAPIMocks(url)
    })

    describe('when there is no props id', () => {
        initKeaTestLogic({
            logic: dashboardLogic,
            props: {
                id: undefined as unknown as number,
            },
            onLogic: (l) => (logic = l),
        })

        it('does not fetch dashboard items on mount', async () => {
            await expectLogic(logic).toNotHaveDispatchedActions(['loadDashboardItems'])
        })
    })

    describe('when props id is set to a number', () => {
        initKeaTestLogic({
            logic: dashboardLogic,
            props: {
                id: 5,
            },
            onLogic: (l) => (logic = l),
        })

        describe('core assumptions', () => {
            it('mounts other logics', async () => {
                await expectLogic(logic).toMount([dashboardsModel, dashboardItemsModel, eventUsageLogic])
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
                            dashboardJson.items.map(({ id }) => id),
                            true
                        ),
                    ])
                    .toMatchValues({
                        refreshStatus: {
                            [dashboardJson.items[0].id]: { loading: true },
                            [dashboardJson.items[1].id]: { loading: true },
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
                            a.payload.item.id === dashboardJson.items[1].id,
                        (a) =>
                            a.type === dashboardsModel.actionTypes.updateDashboardItem &&
                            a.payload.item.id === dashboardJson.items[0].id,
                        // no longer reloading
                        logic.actionCreators.setRefreshStatus(dashboardJson.items[0].id, false),
                        logic.actionCreators.setRefreshStatus(dashboardJson.items[1].id, false),
                    ])
                    .toMatchValues({
                        refreshStatus: {
                            [dashboardJson.items[0].id]: { refreshed: true },
                            [dashboardJson.items[1].id]: { refreshed: true },
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
                    .toDispatchActions([
                        'refreshAllDashboardItems',
                        logic.actionCreators.setRefreshStatuses([dashboardJson.items[0].id], true),
                    ])
                    .toMatchValues({
                        refreshStatus: {
                            [dashboardJson.items[0].id]: { loading: true },
                        },
                        refreshMetrics: {
                            completed: 0,
                            total: 1,
                        },
                    })
                    .toDispatchActionsInAnyOrder([
                        (a) =>
                            a.type === dashboardsModel.actionTypes.updateDashboardItem &&
                            a.payload.item.id === dashboardJson.items[0].id,
                        logic.actionCreators.setRefreshStatus(dashboardJson.items[0].id, false),
                    ])
                    .toMatchValues({
                        refreshStatus: {
                            [dashboardJson.items[0].id]: { refreshed: true },
                        },
                        refreshMetrics: {
                            completed: 1,
                            total: 1,
                        },
                    })
            })
        })
    })
})
