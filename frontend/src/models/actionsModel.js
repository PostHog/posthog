import { kea } from 'kea'
import api from 'lib/api'

const actionContains = (action, event) => {
    return action.steps.filter(step => step.event == event).length > 0
}

export const actionsModel = kea({
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
            () => [selectors.actions],
            actions => {
                let data = [
                    { label: 'Autocapture', options: [] },
                    { label: 'Event', options: [] },
                    { label: 'Pageview', options: [] },
                ]
                actions.forEach(action => {
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
