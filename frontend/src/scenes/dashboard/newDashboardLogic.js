import { kea } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { cancellablePrompt } from 'lib/components/prompt'
import { router } from 'kea-router'
import { message } from 'antd'

// This logic creates a modal to add a new dashboard. It's unique in that when the logic is unmounted,
// for example when changing the URL, the modal is also closed. That would normally happen with the antd prompt.
//
// props:
// - key - unique key for this logic
// - redirect = true/false - redirect to the new dash once it's added
export const newDashboardLogic = kea({
    key: props => props.key,

    actions: () => ({
        addNewDashboard: true,
    }),

    events: ({ cache }) => ({
        beforeUnmount: [
            () => {
                cache.runOnClose && cache.runOnClose()
            },
        ],
    }),

    listeners: ({ cache, props }) => ({
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
        [dashboardsModel.actions.addDashboardSuccess]: ({ dashboard }) => {
            message.success(`Dashboard "${dashboard.name}" created!`)
            if (props.redirect) {
                router.actions.push(`/dashboard/${dashboard.id}`)
            }
        },
    }),
})
