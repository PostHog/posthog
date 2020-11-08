import { kea } from 'kea'
import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

const actionContains = (action, event) => {
    return action.steps.filter((step) => step.event == event).length > 0
}

export const actionsModel = kea({
    connect: {
        values: [featureFlagLogic, ['featureFlags']],
    },
    loaders: ({ props }) => ({
        actions: {
            __default: [],
            loadActions: async () => {
                const response = await api.get(`api/action/?${props.params ? props.params : ''}`)
                return response.results
            },
        },
    }),
    selectors: ({ selectors }) => ({
        actionsGrouped: [
            () => [selectors.actions, selectors.featureFlags],
            (actions, featureFlags) => {
                if (featureFlags['actions-ux-201012']) {
                    // In this experiment we no longer group actions by type
                    return [
                        {
                            label: 'Select an action',
                            options: actions.map((action) => {
                                return { label: action.name, value: action.id }
                            }),
                        },
                    ]
                }

                let data = [
                    { label: 'Autocapture', options: [] },
                    { label: 'Event', options: [] },
                    { label: 'Pageview', options: [] },
                ]
                actions.forEach((action) => {
                    let format = { label: action.name, value: action.id }
                    if (actionContains(action, '$autocapture')) data[0].options.push(format)
                    if (actionContains(action, '$pageview')) data[2].options.push(format)
                    if (!actionContains(action, '$autocapture') && !actionContains(action, '$pageview'))
                        data[1].options.push(format)
                })
                return data
            },
        ],
    }),

    events: ({ actions }) => ({
        afterMount: actions.loadActions,
    }),
})
