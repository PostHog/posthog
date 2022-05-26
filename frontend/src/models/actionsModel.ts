import { kea } from 'kea'
import api from 'lib/api'
import { ActionType } from '~/types'
import type { actionsModelType } from './actionsModelType'

export interface ActionsModelProps {
    params?: string
}

export function findActionName(id: number): string | null {
    return actionsModel.findMounted()?.values.actions.find((a) => a.id === id)?.name || null
}

export const actionsModel = kea<actionsModelType>({
    path: ['models', 'actionsModel'],
    props: {} as ActionsModelProps,
    loaders: ({ props, values }) => ({
        actions: {
            __default: [] as ActionType[],
            loadActions: async () => {
                const response = await api.actions.list(props.params)
                return response.results ?? []
            },
            updateAction: (action: ActionType) => (values.actions || []).map((a) => (action.id === a.id ? action : a)),
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
        actionsById: [
            (s) => [s.actions],
            (actions): Partial<Record<string | number, ActionType>> =>
                Object.fromEntries(actions.map((action) => [action.id, action])),
        ],
    }),

    events: ({ actions }) => ({
        afterMount: () => actions.loadActions(),
    }),
})
