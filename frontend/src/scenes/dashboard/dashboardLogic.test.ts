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

jest.mock('lib/api')

describe('dashboardLogic', () => {
    let logic: BuiltLogic<dashboardLogicType>

    mockAPI(async ({ pathname, searchParams }) => {
        if (pathname === 'api/dashboard/5/') {
            return dashboardJson
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
})
