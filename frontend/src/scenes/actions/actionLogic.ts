import { kea } from 'kea'
import api from 'lib/api'
import type { actionLogicType } from './actionLogicType'
import { ActionType, Breadcrumb } from '~/types'
import { urls } from 'scenes/urls'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export interface ActionLogicProps {
    id?: ActionType['id']
}

export const actionLogic = kea<actionLogicType>({
    props: {} as ActionLogicProps,
    key: (props) => props.id || 'new',
    path: (key) => ['scenes', 'actions', 'actionLogic', key],

    actions: () => ({
        checkIsFinished: (action) => ({ action }),
        setPollTimeout: (pollTimeout) => ({ pollTimeout }),
        setIsComplete: (isComplete) => ({ isComplete }),
    }),
    reducers: () => ({
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
    }),
    selectors: {
        shouldSimplifyActions: [
            () => [featureFlagLogic.selectors.featureFlags],
            (flags) => !!flags[FEATURE_FLAGS.SIMPLIFY_ACTIONS],
        ],
        breadcrumbs: [
            (s) => [s.action, s.shouldSimplifyActions],
            (action, shouldSimplifyActions): Breadcrumb[] => [
                ...(shouldSimplifyActions
                    ? [
                          {
                              name: `Data Management`,
                              path: urls.eventDefinitions(),
                          },
                          {
                              name: 'Events',
                              path: urls.eventDefinitions(),
                          },
                      ]
                    : [
                          {
                              name: 'Data Management',
                              path: urls.actions(),
                          },
                      ]),
                {
                    name: action?.name || 'Unnamed',
                    path: action ? urls.action(action.id) : undefined,
                },
            ],
        ],
    },
    loaders: ({ actions, props }) => ({
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
    }),
    listeners: ({ actions, values }) => ({
        checkIsFinished: ({ action }) => {
            if (action.is_calculating) {
                actions.setPollTimeout(setTimeout(() => actions.loadAction(), 1000))
            } else {
                actions.setIsComplete(new Date())
                values.pollTimeout && clearTimeout(values.pollTimeout)
            }
        },
    }),
    events: ({ values, actions, props }) => ({
        afterMount: () => {
            props.id && actions.loadAction()
        },
        beforeUnmount: () => {
            values.pollTimeout && clearTimeout(values.pollTimeout)
        },
    }),
})
