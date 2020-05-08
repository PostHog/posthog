import { kea } from 'kea'
import api from 'lib/api'
import { dashboardsModel } from '~/models/dashboardsModel'
import { cancellablePrompt } from 'lib/components/prompt'
import { router } from 'kea-router'
import { message } from 'antd'

export const dashboardLogic = kea({
    key: props => props.id,

    actions: () => ({
        addNewDashboard: true,
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
        addNewDashboard: async () => {
            const { cancel, promise } = cancellablePrompt({
                title: 'New dashboard',
                placeholder: 'Please enter a name',
                value: '',
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
                dashboardsModel.actions.addDashboard({ name })
            } catch (e) {}
        },
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
        [dashboardsModel.actions.addDashboardSuccess]: ({ dashboard }) => {
            message.success(`Dashboard "${dashboard.name}" added!`)
            router.actions.push(`/dashboard/${dashboard.id}`)
        },
    }),
})
