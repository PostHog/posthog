import { kea } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { router } from 'kea-router'
import { prompt } from 'lib/logic/prompt'

export const dashboardsLogic = kea({
    actions: () => ({
        addNewDashboard: true,
    }),

    selectors: () => ({
        dashboards: [
            () => [dashboardsModel.selectors.dashboards],
            (dashboards) => dashboards.filter((d) => !d.deleted).sort((a, b) => a.name.localeCompare(b.name)),
        ],
    }),

    listeners: () => ({
        addNewDashboard: async () => {
            prompt({ key: `new-dashboard-dashboards` }).actions.prompt({
                title: 'New dashboard',
                placeholder: 'Please enter a name',
                value: '',
                error: 'You must enter name',
                success: (name) => dashboardsModel.actions.addDashboard({ name }),
            })
        },

        [dashboardsModel.actions.addDashboardSuccess]: ({ dashboard }) => {
            router.actions.push(`/dashboard/${dashboard.id}`)
        },
    }),
})
