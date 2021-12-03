import { BuiltLogic } from 'kea'
import { defaultAPIMocks, mockAPI, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic, truth } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { dashboardLogic, DashboardLogicProps } from 'scenes/dashboard/dashboardLogic'
import _dashboardJson from './__mocks__/dashboard.json'
import { dashboardLogicType } from 'scenes/dashboard/dashboardLogicType'
import { dashboardsModel } from '~/models/dashboardsModel'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { DashboardItemType, DashboardType } from '~/types'

const dashboardJson = _dashboardJson as any as DashboardType

jest.mock('lib/api')

describe('dashboardLogic', () => {
    let logic: BuiltLogic<dashboardLogicType<DashboardLogicProps>>

    mockAPI(async (url) => {
        const { pathname } = url
        if (pathname === `api/projects/${MOCK_TEAM_ID}/dashboards/5/`) {
            return dashboardJson
        } else if (pathname === `api/projects/${MOCK_TEAM_ID}/dashboards/6/`) {
            return {
                ...dashboardJson,
                items: [
                    { ...dashboardJson.items[0], result: null },
                    { ...dashboardJson.items[1], result: null },
                    { ...dashboardJson.items[0], id: 666, short_id: '666' },
                    { ...dashboardJson.items[1], id: 999, short_id: '999' },
                ],
            }
        } else if (pathname === `api/projects/${MOCK_TEAM_ID}/dashboards/7/`) {
            throw new Error('💣')
        } else if (pathname === `api/projects/${MOCK_TEAM_ID}/dashboards/8/`) {
            return {
                ...dashboardJson,
                items: [{ id: 1001, short_id: '1001' }],
            }
        } else if (pathname === `api/projects/${MOCK_TEAM_ID}/insights/1001`) {
            throw new Error('💣')
        } else if (pathname.startsWith(`api/projects/${MOCK_TEAM_ID}/insights/`)) {
            return dashboardJson.items.find(({ id }: any) => String(id) === pathname.split('/')[4])
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

    describe('when the dashboard API errors', () => {
        initKeaTestLogic({
            logic: dashboardLogic,
            props: {
                id: 7,
            },
            onLogic: (l) => (logic = l),
        })

        it('allows consumers to respond', async () => {
            await expectLogic(logic).toMatchValues({
                receivedErrorsFromAPI: true,
            })
        })
    })

    describe('when a dashboard item API errors', () => {
        initKeaTestLogic({
            logic: dashboardLogic,
            props: {
                id: 8,
            },
            onLogic: (l) => (logic = l),
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
        initKeaTestLogic({
            logic: dashboardLogic,
            props: {
                id: 5,
            },
            onLogic: (l) => (logic = l),
        })

        describe('on load', () => {
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
        initKeaTestLogic({
            logic: dashboardLogic,
            props: {
                id: 6,
            },
            onLogic: (l) => (logic = l),
        })

        it('fetches dashboard items on mount', async () => {
            await expectLogic(logic)
                .toDispatchActions(['loadDashboardItemsSuccess'])
                .toMatchValues({
                    allItems: truth(
                        ({ items }) => items.filter((i: DashboardItemType) => i.result === null).length === 2
                    ),
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
                    allItems: truth(
                        ({ items }) => items.filter((i: DashboardItemType) => i.result === null).length === 0
                    ),
                    items: truth((items) => items.length === 4),
                })
        })
    })
})
