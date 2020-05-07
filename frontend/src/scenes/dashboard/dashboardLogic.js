import { kea } from 'kea'
import api from 'lib/api'
import { dashboardsModel } from '~/models/dashboardsModel'
import { cancellablePrompt } from 'lib/components/prompt'
import { message } from 'antd'

export const dashboardLogic = kea({
    key: props => props.id,

    actions: () => ({
        addNewDashboard: true,
    }),

    loaders: ({ props }) => ({
        dashboard: [
            {},
            {
                loadDashboard: async () => {
                    return await api.get(`api/dashboard/${props.id}`)
                },
            },
        ],
    }),

    selectors: ({ selectors, props }) => ({
        items: [() => [selectors.dashboard], dashboard => dashboard.items || []],
        partialDashboard: [
            () => [dashboardsModel.selectors.dashboards, selectors.dashboard],
            (dashboards, dashboard) =>
                Object.assign({}, dashboards.find(d => d.id === parseInt(props.id)) || {}, dashboard),
        ],
    }),

    events: ({ actions, cache }) => ({
        afterMount: [actions.loadDashboard],
        beforeUnmount: [
            () => {
                cache.runOnClose && cache.runOnClose()
            },
        ],
    }),

    listeners: ({ cache }) => ({
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
                await promise
                message.success('Should now create a new dashboard with the name: ' + name)
            } catch (e) {}
        },
    }),
})
