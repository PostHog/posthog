import { kea } from 'kea'
import { dashboardsModel } from '~/models/dashboardsModel'
import { router } from 'kea-router'
import { message } from 'antd'
import { prompt } from 'lib/logic/prompt'

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

    listeners: ({ key, props }) => ({
        addNewDashboard: async () => {
            prompt({ key: `new-dashboard-${key}` }).actions.prompt({
                title: 'New dashboard',
                placeholder: 'Please enter a name',
                value: '',
                error: 'You must enter name',
                success: name => dashboardsModel.actions.addDashboard({ name }),
                failure: () => {},
            })
        },
        [dashboardsModel.actions.addDashboardSuccess]: ({ dashboard }) => {
            message.success(`Dashboard "${dashboard.name}" created!`)
            if (props.redirect) {
                router.actions.push(`/dashboard/${dashboard.id}`)
            }
        },
    }),
})
