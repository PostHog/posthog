import { kea } from 'kea'
import api from 'lib/api'
import { ActionType } from '~/types'
import { actionsModelType } from './actionsModelType'

export const actionsModel = kea<actionsModelType>({
    loaders: ({ props }) => ({
        actions: {
            __default: [] as ActionType[],
            loadActions: async () => {
                const response = await api.get(`api/action/?${props.params ? props.params : ''}`)
                return response.results
            },
        },
    }),
    selectors: ({ selectors }) => ({
        actionsGrouped: [
            () => [selectors.actions],
            (actions: ActionType[]) => {
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
