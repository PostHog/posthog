import { kea } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { router } from 'kea-router'

export const dashboardsLogic = kea({
    actions: () => ({
        addNewDashboard: true,
    }),

    selectors: () => ({
        dashboards: [
            () => [dashboardsModel.selectors.dashboards],
            (dashboards) =>
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
})
