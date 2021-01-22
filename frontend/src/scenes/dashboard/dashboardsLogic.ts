import { kea } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { router } from 'kea-router'
import { dashboardsLogicType } from './dashboardsLogicType'
import { DashboardType } from '~/types'

export const dashboardsLogic = kea<dashboardsLogicType>({
    actions: () => ({
        addNewDashboard: true,
        setNewDashboardDrawer: (shown) => ({ shown }), // Whether the drawer to create a new dashboard should be shown
    }),
    reducers: () => ({
        newDashboardDrawer: [
            false,
            {
                setNewDashboardDrawer: (_, { shown }) => shown,
            },
        ],
    }),
    selectors: () => ({
        dashboards: [
            () => [dashboardsModel.selectors.dashboards],
            (dashboards: DashboardType[]) =>
                dashboards
                    .filter((d) => !d.deleted)
                    .sort((a, b) => (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled')),
        ],
    }),
    listeners: () => ({
        [dashboardsModel.actions.addDashboardSuccess]: ({ dashboard }) => {
            router.actions.push(`/dashboard/${dashboard.id}`)
        },
    }),
    urlToAction: ({ actions }) => ({
        '/dashboard': (_: any, { new: newDashboard }: { new: boolean }) => {
            if (newDashboard !== undefined) {
                actions.setNewDashboardDrawer(true)
            }
        },
    }),
})
