import { kea } from 'kea'
import api from 'lib/api'
import { dashboardsModel } from '~/models/dashboardsModel'
import { prompt } from 'lib/logic/prompt'
import { router } from 'kea-router'

export const dashboardLogic = kea({
    key: props => props.id,

    actions: () => ({
        addNewDashboard: true,
        renameDashboard: true,
        renameDashboardItem: id => ({ id }),
        renameDashboardItemSuccess: item => ({ item }),
    }),

    loaders: ({ props }) => ({
        items: [
            [],
            {
                loadDashboardItems: async () => {
                    try {
                        const { items } = await api.get(`api/dashboard/${props.id}`)
                        return items
                    } catch (error) {
                        if (error.status === 404) {
                            // silently escape
                            return []
                        }
                        throw error
                    }
                },
            },
        ],
    }),

    reducers: () => ({
        items: {
            renameDashboardItemSuccess: (state, { item }) => state.map(i => (i.id === item.id ? item : i)),
        },
    }),

    selectors: ({ props }) => ({
        dashboard: [
            () => [dashboardsModel.selectors.dashboards],
            dashboards => dashboards.find(d => d.id === props.id) || null,
        ],
    }),

    events: ({ actions }) => ({
        afterMount: [actions.loadDashboardItems],
    }),

    listeners: ({ actions, values, key }) => ({
        addNewDashboard: async () => {
            prompt({ key: `new-dashboard-${key}` }).actions.prompt({
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

        renameDashboard: async () => {
            prompt({ key: `rename-dashboard-${key}` }).actions.prompt({
                title: 'Rename dashboard',
                placeholder: 'Please enter the new name',
                value: values.dashboard.name,
                error: 'You must enter name',
                success: name => dashboardsModel.actions.renameDashboard({ id: values.dashboard.id, name }),
            })
        },

        renameDashboardItem: async ({ id }) => {
            prompt({ key: `rename-dashboard-item-${id}` }).actions.prompt({
                title: 'Rename panel',
                placeholder: 'Please enter the new name',
                value: values.items.find(item => item.id === id)?.name,
                error: 'You must enter name',
                success: async name => {
                    const item = await api.update(`api/dashboard_item/${id}`, { name })
                    actions.renameDashboardItemSuccess(item)
                },
            })
        },
    }),
})
