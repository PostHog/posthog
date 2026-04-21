import { expectLogic } from 'kea-test-utils'

import { dashboardWidgetMenusLogic } from 'lib/components/Cards/InsightCard/dashboardWidgetMenusLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

describe('dashboardWidgetMenusLogic', () => {
    beforeEach(() => {
        initKeaTests()
        dashboardsModel.mount()
    })

    it('merges dashboardId, legacy dashboards ids, and dashboard_tiles into dashboardIdsWithThisWidget', async () => {
        const logic = dashboardWidgetMenusLogic({
            instanceKey: 'test',
            dashboardId: 10,
            dashboards: [5, 6],
            dashboard_tiles: [
                { id: 1, dashboard_id: 7 },
                { id: 2, dashboard_id: 10 },
            ],
        })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            dashboardIdsWithThisWidget: new Set([5, 6, 7, 10]),
        })
    })

    it('copyToDestinations excludes the current dashboard and disables rows already placed', async () => {
        dashboardsModel.actions.addDashboardSuccess({
            id: 1,
            name: 'Current',
            user_access_level: AccessControlLevel.Editor,
        } as any)
        dashboardsModel.actions.addDashboardSuccess({
            id: 2,
            name: 'Other',
            user_access_level: AccessControlLevel.Editor,
        } as any)

        const logic = dashboardWidgetMenusLogic({
            instanceKey: 'test',
            dashboardId: 1,
            dashboards: undefined,
            dashboard_tiles: [{ id: 10, dashboard_id: 1 }],
        })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            copyToDestinations: [
                {
                    dashboard: expect.objectContaining({ id: 2, name: 'Other' }),
                    disabledReason: undefined,
                },
            ],
        })
    })

    it('marks a destination disabled when the widget is already placed there (legacy dashboards list)', async () => {
        dashboardsModel.actions.addDashboardSuccess({
            id: 1,
            name: 'A',
            user_access_level: AccessControlLevel.Editor,
        } as any)
        dashboardsModel.actions.addDashboardSuccess({
            id: 2,
            name: 'B',
            user_access_level: AccessControlLevel.Editor,
        } as any)

        const logic = dashboardWidgetMenusLogic({
            instanceKey: 'test',
            dashboardId: 1,
            dashboards: [2],
            dashboard_tiles: [],
        })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            copyToDestinations: [
                {
                    dashboard: expect.objectContaining({ id: 2, name: 'B' }),
                    disabledReason: 'Already on this dashboard',
                },
            ],
        })
    })
})
