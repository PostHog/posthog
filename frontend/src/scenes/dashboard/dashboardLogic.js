import { kea } from 'kea'
import api from 'lib/api'
import { dashboardsModel } from '~/models/dashboardsModel'
import { cancellablePrompt } from 'lib/components/prompt'

export const dashboardLogic = kea({
    key: props => props.id,

    actions: () => ({
        renameDashboard: true,
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

    selectors: ({ props }) => ({
        dashboard: [
            () => [dashboardsModel.selectors.dashboards],
            dashboards => dashboards.find(d => d.id === props.id) || null,
        ],
    }),

    events: ({ actions, cache }) => ({
        afterMount: [actions.loadDashboardItems],
        beforeUnmount: [
            () => {
                cache.runOnClose && cache.runOnClose()
            },
        ],
    }),

    listeners: ({ cache, values }) => ({
        renameDashboard: async () => {
            const { cancel, promise } = cancellablePrompt({
                title: 'Rename dashboard',
                placeholder: 'Please enter the new name',
                value: values.dashboard.name,
                rules: [
                    {
                        required: true,
                        message: 'You must enter name',
                    },
                ],
            })
            cache.runOnClose = cancel

            try {
                const name = await promise
                dashboardsModel.actions.renameDashboard({ id: values.dashboard.id, name })
            } catch (e) {}
        },
    }),
})
