import { kea } from 'kea'
import api from 'lib/api'
import { ActionType } from '~/types'
import { actionsModelType } from './actionsModelType'

interface ActionsModelProps {
    params?: string
}

export function findActionName(id: number): string | null {
    return actionsModel.findMounted()?.values.actions.find((a) => a.id === id)?.name || null
}

export const actionsModel = kea<actionsModelType<ActionsModelProps>>({
    path: ['models', 'actionsModel'],
    props: {} as ActionsModelProps,
    loaders: ({ props }) => ({
        actions: {
            __default: [] as ActionType[],
            loadActions: async () => {
                const response = await api.actions.list(props.params)
                return response.results ?? []
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
        afterMount: () => actions.loadActions(),
    }),
})
