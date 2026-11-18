import { router } from 'kea-router'
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

    it('merges dashboardId and live dashboard_tiles into dashboardIdsWithThisWidget, skipping soft-deleted tiles', async () => {
        const logic = dashboardWidgetMenusLogic({
            instanceKey: 'test',
            dashboardId: 10,
            dashboard_tiles: [
                { id: 1, dashboard_id: 7 },
                { id: 2, dashboard_id: 10 },
                { id: 3, dashboard_id: 8, deleted: true },
            ],
        })
        logic.mount()

        await expectLogic(logic).toMatchValues({
            dashboardIdsWithThisWidget: new Set([7, 10]),
        })
    })

    it('keeps copyToDestinations stable when a caller passes a new empty tiles array', () => {
        const logic = dashboardWidgetMenusLogic({ instanceKey: 'test', dashboardId: 1, dashboard_tiles: [] })
        logic.mount()
        const destinations = logic.values.copyToDestinations

        dashboardWidgetMenusLogic({ instanceKey: 'test', dashboardId: 1, dashboard_tiles: [] })
        // The selectors recompute only when the store state changes, and any action does that in the app.
        router.actions.push('/elsewhere')

        expect(logic.values.copyToDestinations).toBe(destinations)
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

    it('marks a destination disabled when the widget is already placed there', async () => {
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
            dashboard_tiles: [{ id: 11, dashboard_id: 2 }],
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
