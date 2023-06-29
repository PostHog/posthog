import { kea } from 'kea'
import api from 'lib/api'
import type { actionLogicType } from './actionLogicType'
import { ActionType, Breadcrumb } from '~/types'
import { urls } from 'scenes/urls'

export interface ActionLogicProps {
    id?: ActionType['id']
}

export const actionLogic = kea<actionLogicType>({
    props: {} as ActionLogicProps,
    key: (props) => props.id || 'new',
    path: (key) => ['scenes', 'actions', 'actionLogic', key],

    selectors: {
        breadcrumbs: [
            (s) => [s.action],
            (action): Breadcrumb[] => [
                {
                    name: `Data Management`,
                    path: urls.eventDefinitions(),
                },
                {
                    name: 'Actions',
                    path: urls.actions(),
                },
                {
                    name: action?.name || 'Unnamed',
                    path: action ? urls.action(action.id) : undefined,
                },
            ],
        ],
    },
    loaders: ({ props }) => ({
        action: {
            loadAction: async () => {
                if (!props.id) {
                    throw new Error('Cannot fetch an unsaved action from the API.')
                }
                const action = await api.actions.get(props.id)
                return action
            },
        },
    }),
    events: ({ actions, props }) => ({
        afterMount: () => {
            props.id && actions.loadAction()
        },
    }),
})
