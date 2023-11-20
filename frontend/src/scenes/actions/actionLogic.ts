import { loaders } from 'kea-loaders'
import { kea, props, key, path, actions, reducers, selectors, listeners, events } from 'kea'
import api from 'lib/api'
import type { actionLogicType } from './actionLogicType'
import { ActionType, Breadcrumb } from '~/types'
import { urls } from 'scenes/urls'
import { Scene } from 'scenes/sceneTypes'
import { DataManagementTab } from 'scenes/data-management/DataManagementScene'

export interface ActionLogicProps {
    id?: ActionType['id']
}

export const actionLogic = kea<actionLogicType>([
    props({} as ActionLogicProps),
    key((props) => props.id || 'new'),
    path((key) => ['scenes', 'actions', 'actionLogic', key]),
    actions(() => ({
        checkIsFinished: (action) => ({ action }),
        setPollTimeout: (pollTimeout) => ({ pollTimeout }),
        setIsComplete: (isComplete) => ({ isComplete }),
    })),
    loaders(({ actions, props }) => ({
        action: {
            loadAction: async () => {
                actions.setIsComplete(false)
                if (!props.id) {
                    throw new Error('Cannot fetch an unsaved action from the API.')
                }
                const action = await api.actions.get(props.id)
                actions.checkIsFinished(action)
                return action
            },
        },
    })),
    reducers(() => ({
        pollTimeout: [
            null as number | null,
            {
                setPollTimeout: (_, { pollTimeout }) => pollTimeout,
            },
        ],
        isComplete: [
            false as boolean,
            {
                setIsComplete: (_, { isComplete }) => isComplete,
            },
        ],
    })),
    selectors({
        breadcrumbs: [
            (s) => [s.action],
            (action): Breadcrumb[] => [
                {
                    key: Scene.DataManagement,
                    name: `Data Management`,
                    path: urls.eventDefinitions(),
                },
                {
                    key: DataManagementTab.Actions,
                    name: 'Actions',
                    path: urls.actions(),
                },
                {
                    key: action?.id || 'new',
                    name: action?.name || 'Unnamed',
                    path: action ? urls.action(action.id) : undefined,
                },
            ],
        ],
    }),
    listeners(({ actions, values }) => ({
        checkIsFinished: ({ action }) => {
            if (action.is_calculating) {
                actions.setPollTimeout(setTimeout(() => actions.loadAction(), 1000))
            } else {
                actions.setIsComplete(new Date())
                values.pollTimeout && clearTimeout(values.pollTimeout)
            }
        },
    })),
    events(({ values, actions, props }) => ({
        afterMount: () => {
            props.id && actions.loadAction()
        },
        beforeUnmount: () => {
            values.pollTimeout && clearTimeout(values.pollTimeout)
        },
    })),
])
