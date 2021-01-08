import { kea } from 'kea'
import api from 'lib/api'

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
            (actions) => {
                return [
                    {
                        label: 'Select an action',
                        options: actions.map((action) => {
                            return { label: action.name, value: action.id }
                        }),
                    },
                ]
            },
        ],
    }),

    events: ({ actions }) => ({
        afterMount: actions.loadActions,
    }),
})
