import { kea } from 'kea'
import api from 'lib/api'
import { ActionType } from '~/types'
import { teamLogic } from '../scenes/teamLogic'
import { actionsModelType } from './actionsModelType'

interface ActionsModelProps {
    params?: string
}

export const actionsModel = kea<actionsModelType<ActionsModelProps>>({
    props: {} as ActionsModelProps,
    loaders: ({ props }) => ({
        actions: {
            __default: [] as ActionType[],
            loadActions: async () => {
                const response = await api.get(
                    `api/projects/${teamLogic.values.currentTeamId}/actions/?${props.params ? props.params : ''}`
                )
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
        afterMount: () => actions.loadActions(),
    }),
})
