import { kea } from 'kea'
import api from 'lib/api'
import { ActionType } from '~/types'
import { getProjectBasedLogicKeyBuilder, ProjectBasedLogicProps } from '../lib/utils/logics'
import { actionsModelType } from './actionsModelType'

interface ActionsModelProps extends ProjectBasedLogicProps {
    params?: string
}

export const actionsModel = kea<actionsModelType<ActionsModelProps>>({
    props: {} as ActionsModelProps,
    key: getProjectBasedLogicKeyBuilder(),
    loaders: ({ props }) => ({
        actions: {
            __default: [] as ActionType[],
            loadActions: async () => {
                const response = await api.get(
                    `api/projects/${props.teamId}/actions/?${props.params ? props.params : ''}`
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

    events: ({ actions, props }) => ({
        afterMount: () => props.teamId && actions.loadActions(),
    }),
})
