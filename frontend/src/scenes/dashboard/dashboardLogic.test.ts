import { BuiltLogic } from 'kea'
import { mockAPI } from 'lib/api.mock'
import { expectLogic, initKeaTestLogic } from '~/test/kea-test-utils'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import dashboardJson from './__mocks__/dashboard.json'
import { truth } from '~/test/kea-test-utils/jest'
import { dashboardLogicType } from 'scenes/dashboard/dashboardLogicType'
import { dashboardsModel } from '~/models/dashboardsModel'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'

jest.mock('lib/api')

describe('dashboardLogic', () => {
    let logic: BuiltLogic<dashboardLogicType>

    mockAPI(async ({ pathname, searchParams }) => {
        if (pathname === 'api/dashboard/5/') {
            return dashboardJson
        } else if (pathname.startsWith('api/dashboard_item/')) {
            return dashboardJson.items.find(({ id }) => id === parseInt(pathname.split('/')[2]))
        } else if (pathname === '_preflight/') {
            return { is_clickhouse_enabled: true }
        } else {
            throw new Error(`Unmocked fetch to: ${pathname} with params: ${JSON.stringify(searchParams)}`)
        }
    })

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
            expectLogic(logic)
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

    describe('reload all items', () => {
        it('reloads when called', async () => {
            await expectLogic(logic, () => {
                logic.actions.refreshAllDashboardItemsManual()
            })
                // starts loading
                .toDispatchActions(['refreshAllDashboardItemsManual', 'refreshAllDashboardItems'])
                // sets the "reloading" status
                .toDispatchActions([
                    logic.actionCreators.setRefreshStatus(dashboardJson.items[0].id, true),
                    logic.actionCreators.setRefreshStatus(dashboardJson.items[1].id, true),
                ])
                .toMatchValues({
                    refreshStatus: {
                        172: { loading: true },
                        175: { loading: true },
                    },
                })
                // calls the "setCachedResults" directly on the sub-logics (trendsLogic.172 this case)
                .toDispatchActions(trendsLogic({ dashboardItemId: 172 }), ['setCachedResults'])
                .toDispatchActions(dashboardsModel, ['updateDashboardItem'])
                .toDispatchActions(trendsLogic({ dashboardItemId: 177 }), ['setCachedResults'])
                .toDispatchActions(dashboardsModel, ['updateDashboardItem'])
                // no longer reloading
                .toDispatchActions([
                    logic.actionCreators.setRefreshStatus(dashboardJson.items[0].id, false),
                    logic.actionCreators.setRefreshStatus(dashboardJson.items[1].id, false),
                ])
                .delay(1000)
                .printActions()
                .toDispatchActions([])
        })
    })
})
