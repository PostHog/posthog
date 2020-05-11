import { kea } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { router } from 'kea-router'
import { prompt } from 'lib/logic/prompt'

export const dashboardsLogic = kea({
    actions: () => ({
        addNewDashboard: true,
        redirectToFirstDashboard: true,
    }),

    events: ({ actions }) => ({
        afterMount: [actions.redirectToFirstDashboard],
    }),

    listeners: ({ sharedListeners }) => ({
        redirectToFirstDashboard: sharedListeners.redirectToFirstDashboard,
        [dashboardsModel.actions.loadDashboardsSuccess]: sharedListeners.redirectToFirstDashboard,

        addNewDashboard: async () => {
            prompt({ key: `new-dashboard-dashboards` }).actions.prompt({
                title: 'New dashboard',
                placeholder: 'Please enter a name',
                value: '',
                error: 'You must enter name',
                success: name => dashboardsModel.actions.addDashboard({ name }),
            })
        },

        [dashboardsModel.actions.addDashboardSuccess]: ({ dashboard }) => {
            router.actions.push(`/dashboard/${dashboard.id}`)
        },
    }),

    sharedListeners: () => ({
        redirectToFirstDashboard: () => {
            const { dashboards } = dashboardsModel.values
            const dashboard = dashboards.find(d => !d.deleted)
            if (dashboard) {
                router.actions.push(`/dashboard/${dashboard.id}`)
            }
        },
    }),
})
